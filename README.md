# SubTracker MVP run and test guide

## Prerequisites
- Python 3.10+ (recommended 3.11)
- `pip`, `venv`

## 1) Create and activate a virtual environment
```bash
cd backend
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (PowerShell):
# .\.venv\Scripts\Activate.ps1
```

## 2) Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 3) Configure environment
```bash
cd backend
cp .env.example .env
# (Optional for Plaid tests) put your PLAID_CLIENT_ID and PLAID_SECRET sandbox creds into .env
# AWS keys are empty and will use MOCK_TEXTRACT=1 (mock Adobe receipt)
```

## 4) Start the server
```bash
python app.py
# Server listens on: http://localhost:5000
```

### Health check
```bash
curl -s http://localhost:5000/api/ping | jq
```
#### expected:
```json
{
  "msg": "pong",
  "ok": true
}
```

---

## No-Plaid Demo (seeded synthetic data)
Seed synthetic monthly transactions, run detection, and inspect results.

```bash
# Seed test transactions (manually inserted with no sandbox)
curl -s -X POST http://localhost:5000/api/seed | jq
```
#### expected:
```json
{ "ok": true, "inserted": 4 }
```

```bash
# Run detection (find monthly subscriptions, compute next_expected = last_tx + 30 days)
curl -s -X POST http://localhost:5000/api/detect | jq
```
#### expected (simplified):
```json
{
  "subscriptions": [
    { "id": 1, "vendor": "Netflix", "interval": "monthly", "status": "inferred", "next_expected": "2025-10-08" },
    { "id": 2, "vendor": "Adobe Inc.", "interval": "monthly", "status": "inferred", "next_expected": "2025-10-05" },
    { "id": 3, "vendor": "Spotify", "interval": "monthly", "status": "inferred", "next_expected": "2025-10-02" }
  ]
}
```

```bash
# View detected subscriptions
curl -s http://localhost:5000/api/subscriptions | jq
```

```bash
# List vendors (to find IDs if needed)
curl -s http://localhost:5000/api/vendors | jq
```
#### expected:
```json
{
  "vendors": [
    { "id": 1, "name": "Netflix" },
    { "id": 2, "name": "Adobe Inc." },
    { "id": 3, "name": "Spotify" }
  ]
}
```

```bash
# Inspect transactions for a specific vendor_id (replace 1 with the actual ID)
curl -s "http://localhost:5000/api/transactions?vendor_id=1&limit=50" | jq
```
#### expected (simplified):
```json
{
  "transactions": [
    { "id": 1, "vendor_name": "Netflix", "amount": 15.99, "date": "2025-08-08" },
    { "id": 2, "vendor_name": "Netflix", "amount": 15.99, "date": "2025-09-08" }
  ]
}
```

---

## Plaid Sandbox Demo 
```bash
# 1) Create a sandbox public token
PUB=$(curl -s -X POST http://localhost:5000/api/plaid/sandbox_public_token | jq -r '.public_token')
```

```bash
# 2) Exchange public_token -> access_token (stored in memory)
curl -s -X POST http://localhost:5000/api/plaid/exchange   -H "Content-Type: application/json"   -d "{\"public_token\":\"$PUB\"}" | jq
```
#### expected:
```json
{ "ok": true }
```

```bash
# 3) Pull last ~120 days of transactions into SQLite
curl -s http://localhost:5000/api/plaid/transactions | jq
```
#### expected (simplified):
```json
{ "saved": 30 }
```

```bash
# 4) Run detection
curl -s -X POST http://localhost:5000/api/detect | jq
```

```bash
# 5) View results
curl -s http://localhost:5000/api/subscriptions | jq
curl -s http://localhost:5000/api/vendors | jq

```

---

## Invoice Ingestion (Textract — MOCK mode)
With `MOCK_TEXTRACT=1` (default when AWS keys are empty), any uploaded file produces a predictable “Adobe Inc.” invoice and stores it in SQLite.

```bash
# Upload any file (contents ignored in MOCK mode)
curl -s -F "file=@/etc/hosts" http://localhost:5000/api/textract | jq
```
#### expected:
```json
{
  "ok": true,
  "parsed": {
    "vendor": "Adobe Inc.",
    "total": 29.99,
    "invoice_date": "2025-07-01",
    "billing_period": "monthly"
  }
}
```

---

## Manage Subscriptions (PATCH)
Manually update a subscription (status, interval, next_expected) to simulate user actions.

```bash
# Example: set subscription #1 to active & monthly and add a next_expected date
curl -s -X PATCH http://localhost:5000/api/subscriptions/3   -H "Content-Type: application/json"   -d '{"status":"active","interval":"monthly","next_expected":"2025-10-01"}' | jq
```
#### expected:
```json
{
  "ok": true,
  "subscription": {
    "id": 1,
    "vendor": "Netflix",
    "status": "active",
    "interval": "monthly",
    "next_expected": "2025-10-01"
  }
}
```

```bash
# Verify changes
curl -s http://localhost:5000/api/subscriptions | jq
```

---

## (Optional) Reset local DB
```bash
# Stop the server, then:
rm -f demo.db
# Start again:
python app.py
```
