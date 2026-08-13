# Humanarties — landing page

A single-scroll landing page validating demand for **Human art**, a marketplace for
original wall art from verified human artists. Built for Azure Static Web Apps
with a Python Azure Function handling email signups.ƒ

## Project structure

```
/
├── src/                      # static frontend
│   ├── index.html
│   ├── privacy.html
│   ├── styles.css
│   └── main.js
├── api/                      # Python Azure Function (v2 programming model)
│   ├── function_app.py       # POST /api/subscribe
│   ├── host.json
│   ├── requirements.txt
│   └── local.settings.json.example
├── staticwebapp.config.json
└── .gitignore
```

## What it does

- Three signup forms (hero, founding-patron band, footer) all post to
  `/api/subscribe`.
- The function validates the email, checks a honeypot field for bots, and
  upserts the subscriber into an Azure Table Storage table called
  `Subscribers` (keyed by a hash of the email, so re-submitting just updates
  the timestamp instead of creating duplicates).
- No purchase, account, or payment flow — this page's only job is capturing
  interest and emails.

## Running locally

You'll need:
- [Azure Static Web Apps CLI](https://learn.microsoft.com/azure/static-web-apps/local-development) (`npm install -g @azure/static-web-apps-cli`)
- [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) v4
- Python 3.10+ 
- [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite) for local table storage emulation (or a real Azure Storage account)

Steps:

```bash
# 1. Copy the local settings template
cp api/local.settings.json.example api/local.settings.json

# 2. Install Python deps
cd api && pip install -r requirements.txt && cd ..

# 3. Start Azurite in a separate terminal (if testing locally)
azurite

# 4. Run the whole app (frontend + API together)
swa start src --api-location api
```

The page will be available at `http://localhost:4280`, with `/api/subscribe`
proxied through to the Function.

## Deploying to Azure

1. Create an **Azure Static Web App** resource, linked to this repo (the
   Azure portal / GitHub integration will generate a deployment workflow
   automatically). Set:
   - App location: `src`
   - API location: `api`
   - Output location: *(leave blank — static HTML, no build step)*
2. Create an **Azure Storage account** (Standard, LRS is plenty for this scale).
3. In the Static Web App's **Configuration / Application settings**, add:
   - `AZURE_STORAGE_CONNECTION_STRING` — the storage account's connection string
4. Push to your connected branch — the GitHub Action deploys both the static
   site and the linked Function automatically.


