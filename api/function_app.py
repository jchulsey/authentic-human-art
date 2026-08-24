"""
Humanarties — email capture API.

Single endpoint, POST /api/subscribe, called from the landing page's
signup forms (hero, founding-patron band, and footer).

Two responsibilities:
  1. Rate-limit by client IP (fixed window, backed by Table Storage) to
     blunt scripted abuse before doing any real work.
  2. Validate and store each signup in Table Storage. Uses a hash of the
     email as the row key so re-submitting the same email updates the
     existing row instead of creating a duplicate.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
TABLE_NAME = "Subscribers"
ALLOWED_SOURCES = {"hero", "patron", "footer", "unknown"}

# --- Rate limiting ---------------------------------------------------------
# Fixed-window limiter keyed by client IP, backed by Table Storage. A plain
# in-memory counter wouldn't work here: Consumption-plan Functions are
# stateless and can be served by a different instance on every request, so
# the counter has to live somewhere shared. Table Storage is already wired
# up for subscribers, so it's the simplest option at this scale rather than
# adding a dedicated cache (e.g. Redis) for an MVP validation page.
RATE_LIMIT_TABLE = "RateLimits"
RATE_LIMIT_MAX_REQUESTS = 5
RATE_LIMIT_WINDOW_SECONDS = 15 * 60  # 15 minutes

# TEMPORARY: set DEBUG_ERRORS=true as an app setting to include the real
# exception type/message in 500 responses while troubleshooting. Turn this
# back off (or delete the setting) once things are working — error internals
# shouldn't be exposed to the public in normal operation.
DEBUG_ERRORS = os.environ.get("DEBUG_ERRORS", "false").strip().lower() == "true"


def _json_response(body: dict, status_code: int, extra_headers: dict | None = None) -> func.HttpResponse:
    headers = {"Cache-Control": "no-store"}
    if extra_headers:
        headers.update(extra_headers)
    return func.HttpResponse(
        json.dumps(body),
        status_code=status_code,
        mimetype="application/json",
        headers=headers,
    )


def _error_response(message: str, status_code: int, exc: Exception | None = None) -> func.HttpResponse:
    body = {"message": message}
    if DEBUG_ERRORS and exc is not None:
        body["debug"] = f"{type(exc).__name__}: {exc}"
    return _json_response(body, status_code)


def _get_client_ip(req: func.HttpRequest) -> str:
    """
    Static Web Apps proxies API requests through its edge, so the caller's
    real IP arrives via a forwarding header rather than a raw socket.
    """
    forwarded_for = req.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    azure_client_ip = req.headers.get("X-Azure-ClientIP")
    if azure_client_ip:
        return azure_client_ip.strip()
    return "unknown"
 
 
def _get_service_client() -> TableServiceClient:
    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    return TableServiceClient.from_connection_string(connection_string)
 
 
def _check_rate_limit(service_client: TableServiceClient, ip: str) -> bool:
    """
    Returns True if this request is allowed. Uses a simple fixed window:
    the first request from an IP starts a window; further requests within
    RATE_LIMIT_WINDOW_SECONDS increment a counter; once the counter exceeds
    RATE_LIMIT_MAX_REQUESTS, further requests are rejected until the window
    rolls over. Good enough at this traffic scale — no need for a more
    precise sliding-window or token-bucket implementation yet.
    """
    # create_table_if_not_exists lives on TableServiceClient, not TableClient.
    service_client.create_table_if_not_exists(RATE_LIMIT_TABLE)
    table_client = service_client.get_table_client(RATE_LIMIT_TABLE)
 
    row_key = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
 
    try:
        entity = table_client.get_entity(partition_key="ratelimit", row_key=row_key)
    except ResourceNotFoundError:
        entity = None
 
    if entity is not None:
        window_start = datetime.fromisoformat(entity["WindowStart"])
        if (now - window_start).total_seconds() <= RATE_LIMIT_WINDOW_SECONDS:
            if entity.get("Count", 0) >= RATE_LIMIT_MAX_REQUESTS:
                return False
            entity["Count"] = entity.get("Count", 0) + 1
            table_client.upsert_entity(entity)
            return True
 
    # No prior entry, or the previous window has expired — start fresh.
    table_client.upsert_entity(
        {
            "PartitionKey": "ratelimit",
            "RowKey": row_key,
            "WindowStart": now.isoformat(),
            "Count": 1,
        }
    )
    return True
 
 
@app.route(route="subscribe", methods=["POST"])
def subscribe(req: func.HttpRequest) -> func.HttpResponse:
    try:
        service_client = _get_service_client()
    except KeyError as exc:
        logging.exception("AZURE_STORAGE_CONNECTION_STRING is not configured.")
        return _error_response(
            "Something went wrong on our end. Please try again shortly.", 500, exc
        )
    except Exception as exc:
        logging.exception("Failed to create the Table Storage service client.")
        return _error_response(
            "Something went wrong on our end. Please try again shortly.", 500, exc
        )
 
    # Rate limit before doing any other work, so abusive traffic is cheap to reject.
    client_ip = _get_client_ip(req)
    try:
        allowed = _check_rate_limit(service_client, client_ip)
    except Exception:
        # Fail open — a broken rate limiter shouldn't block real signups.
        logging.exception("Rate limit check failed — allowing the request through.")
        allowed = True
 
    if not allowed:
        logging.warning("Rate limit exceeded for IP %s", client_ip)
        return _json_response(
            {"message": "Too many attempts. Please try again in a few minutes."},
            429,
            extra_headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
        )
 
    try:
        payload = req.get_json()
    except ValueError:
        return _json_response({"message": "Invalid request body."}, 400)
 
    email = (payload.get("email") or "").strip().lower()
    honeypot = (payload.get("company") or "").strip()
    source = (payload.get("source") or "unknown").strip().lower()
 
    if source not in ALLOWED_SOURCES:
        source = "unknown"
 
    # Bots tend to fill every field, including ones hidden from real users.
    # Pretend success so we don't tip them off, but skip the write.
    if honeypot:
        logging.info("Honeypot triggered — ignoring submission.")
        return _json_response(
            {"message": "You're on the list — check your inbox for a confirmation soon."},
            200,
        )
 
    if not email or not EMAIL_RE.match(email):
        return _json_response({"message": "Enter a valid email address."}, 400)
 
    try:
        service_client.create_table_if_not_exists(SUBSCRIBERS_TABLE)
        table_client = service_client.get_table_client(SUBSCRIBERS_TABLE)
    except Exception as exc:
        logging.exception("Failed to access the Subscribers table.")
        return _error_response(
            "Something went wrong on our end. Please try again shortly.", 500, exc
        )
 
    row_key = hashlib.sha256(email.encode("utf-8")).hexdigest()
 
    entity = {
        "PartitionKey": "subscriber",
        "RowKey": row_key,
        "Email": email,
        "Source": source,
        "SubscribedAt": datetime.now(timezone.utc).isoformat(),
        "Consented": True,
    }
 
    try:
        table_client.upsert_entity(entity=entity)
    except Exception as exc:
        logging.exception("Failed to write subscriber entity.")
        return _error_response(
            "Something went wrong on our end. Please try again shortly.", 500, exc
        )
 
    return _json_response(
        {"message": "You're on the list — check your inbox for a confirmation soon."},
        200,
    )
