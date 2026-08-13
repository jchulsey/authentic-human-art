"""
Humanarties — email capture API.

Single endpoint, POST /api/subscribe, called from the landing page's
signup forms (hero, founding-patron band, and footer).

Stores each signup in Azure Table Storage. Uses a hash of the email as
the row key so re-submitting the same email updates the existing row
instead of creating a duplicate.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import azure.functions as func
from azure.data.tables import TableServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
TABLE_NAME = "Subscribers"
ALLOWED_SOURCES = {"hero", "patron", "footer", "unknown"}


def _json_response(body: dict, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body),
        status_code=status_code,
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )


def _get_table_client():
    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    service_client = TableServiceClient.from_connection_string(connection_string)
    table_client = service_client.get_table_client(TABLE_NAME)
    # Safe to call every invocation — no-ops if the table already exists.
    table_client.create_table_if_not_exists()
    return table_client


@app.route(route="subscribe", methods=["POST"])
def subscribe(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = req.get_json()
    except ValueError:
        return _json_response(
            {"message": "Invalid request body."}, 400
        )

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
        return _json_response(
            {"message": "Enter a valid email address."}, 400
        )

    try:
        table_client = _get_table_client()
    except KeyError:
        logging.exception("AZURE_STORAGE_CONNECTION_STRING is not configured.")
        return _json_response(
            {"message": "Something went wrong on our end. Please try again shortly."},
            500,
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
    except Exception:
        logging.exception("Failed to write subscriber entity.")
        return _json_response(
            {"message": "Something went wrong on our end. Please try again shortly."},
            500,
        )

    return _json_response(
        {"message": "You're on the list — check your inbox for a confirmation soon."},
        200,
    )
