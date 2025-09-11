import os
import json

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from database import engine, SessionLocal
from models import Base, Transaction, Vendor, Invoice, Subscription
from detection import detect_basic_subscriptions
from datetime import date, timedelta

# Plaid
from plaid.api import plaid_api
from plaid import Configuration, ApiClient, Environment
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest

# AWS
import boto3
from werkzeug.utils import secure_filename

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")
    CORS(app)

    Base.metadata.create_all(bind=engine)

    # Plaid client 
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    host = {
        "sandbox":    Environment.Sandbox,
        "development": Environment.Development,
        "production":  Environment.Production,
    }[env]

    configuration = Configuration(
        host=host,
        api_key={
            "clientId": os.getenv("PLAID_CLIENT_ID", ""),
            "secret": os.getenv("PLAID_SECRET", ""),
        },
    )

    api_client = ApiClient(configuration)
    plaid_client = plaid_api.PlaidApi(api_client)


    def db() -> Session:
        return SessionLocal()

    @app.get("/api/ping")
    def ping():
        return {"ok": True, "msg": "pong"}

    # Plaid link - bank selection pop-up
    @app.post("/api/plaid/link_token")
    def create_link_token():
        req = LinkTokenCreateRequest(
            user={"client_user_id": "demo-user-123"},
            client_name="SubTracker Demo",
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
        )
        resp = plaid_client.link_token_create(req)
        return jsonify(resp.to_dict())

    # Plaid: change public_token -> access_token 
    @app.post("/api/plaid/exchange")
    def exchange_public_token():
        public_token = request.json.get("public_token")
        if not public_token:
            return {"error":"public_token required"}, 400
        ex_req = ItemPublicTokenExchangeRequest(public_token=public_token)
        ex_resp = plaid_client.item_public_token_exchange(ex_req)
        # In demo we store access_token in memory only 
        app.config["PLAID_ACCESS_TOKEN"] = ex_resp.to_dict()["access_token"]
        return {"ok": True}

    def _to_jsonable(obj):
    # make obj JSON-serializable (e.g. convert date to str)
        return json.loads(json.dumps(obj, default=str))

    # Get Plaid transactions and store them in SQLite
    @app.get("/api/plaid/transactions")
    def get_transactions():
        access_token = app.config.get("PLAID_ACCESS_TOKEN")
        if not access_token:
            return {"error": "Link account first (/api/plaid/link_token + /api/plaid/exchange)"}, 400

        from datetime import date, timedelta
        start_date = date.today() - timedelta(days=120)
        end_date = date.today()

        request_options = TransactionsGetRequestOptions(count=50)
        t_req = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,  
            end_date=end_date,
            options=request_options
        )
        t_resp = plaid_client.transactions_get(t_req).to_dict()

        txns = t_resp.get("transactions", [])
        s = db()
        saved = 0
        try:
            for t in txns:
                # duplicates protection transaction_id
                if s.query(Transaction).filter_by(plaid_txn_id=t.get("transaction_id")).first():
                    continue

                # date to string 'YYYY-MM-DD'
                t_date = t.get("date")
                date_str = t_date.isoformat() if hasattr(t_date, "isoformat") else (str(t_date) if t_date is not None else None)

                merchant = t.get("merchant_name") or t.get("name")
                obj = Transaction(
                    plaid_txn_id=t.get("transaction_id"),
                    merchant_name=merchant,
                    amount=t.get("amount"),
                    iso_currency_code=t.get("iso_currency_code"),
                    date=date_str,              
                    raw=_to_jsonable(t),        # store full raw json data
                )
                s.add(obj)
                saved += 1
            s.commit()
        finally:
            s.close()

        return {"saved": saved}

    @app.post("/api/plaid/sandbox_public_token")
    def sandbox_public_token():
        req = SandboxPublicTokenCreateRequest(
            institution_id="ins_109509",  # First Platypus Bank (sandbox)
            initial_products=[Products("transactions")]
        )
        resp = plaid_client.sandbox_public_token_create(req)
        return jsonify(resp.to_dict())    

    # Basic detection --- runs the detection.py file
    @app.post("/api/detect")
    def run_detection():
        s = db()
        try:
            detect_basic_subscriptions(s)
            subs = s.query(Subscription).all()
            out = []
            for sub in subs:
                vendor = s.query(Vendor).get(sub.vendor_id) if sub.vendor_id else None
                out.append({
                    "id": sub.id,
                    "vendor": vendor.name if vendor else None,
                    "interval": sub.interval,
                    "status": sub.status,
                    "next_expected": sub.next_expected,   
                    "confidence": getattr(sub, "confidence", None),  # (optional for future implementation)
                })
            return {"subscriptions": out}
        finally:
            s.close()

    @app.post("/api/seed")
    def seed_demo_data():
        from datetime import date, timedelta
        s = SessionLocal()
        try:
            base = date.today()
            demo = [
                ("Netflix",    [base, base - timedelta(days=30), base - timedelta(days=60)], 15.99),
                ("Adobe Inc.", [base - timedelta(days=5), base - timedelta(days=35), base - timedelta(days=65)], 29.99),
                ("Spotify",    [base - timedelta(days=2), base - timedelta(days=32), base - timedelta(days=62)], 9.99),
                # Starbucks - should be ignored due to NAME_BLACKLIST
                ("Starbucks",  [base - timedelta(days=3), base - timedelta(days=11), base - timedelta(days=20)], 5.50),
            ]
            for name, dates, amt in demo:
                for d in dates:
                    s.add(Transaction(
                        vendor_id=None, plaid_txn_id=None,
                        merchant_name=name, amount=amt, iso_currency_code="USD",
                        date=d.isoformat(), raw={"seed": True}
                    ))
            s.commit()
            return {"ok": True, "inserted": len(demo)}
        finally:
            s.close()

    # Textract: load PDF and analyze
    @app.post("/api/textract")
    def textract_analyze():
        file = request.files.get("file")
        if not file:
            return {"error":"file required"}, 400

        filename = secure_filename(file.filename or "invoice.pdf")
        path = os.path.join("/tmp", filename)
        file.save(path)

        if os.getenv("MOCK_TEXTRACT","0") == "1" or not os.getenv("AWS_ACCESS_KEY_ID"):
            result = {
                "vendor": "Adobe Inc.",
                "total": 29.99,
                "invoice_date": "2025-07-01",
                "billing_period": "monthly",
                "raw": {"mock": True}
            }
        else:
            client = boto3.client("textract", region_name=os.getenv("AWS_REGION","us-east-1"))
            with open(path, "rb") as f:
                data = f.read()
            # For quick demo we use analyze_expense
            resp = client.analyze_expense(Document={"Bytes": data})
            # Simple field extraction
            def find_field(blocks, name):
                for doc in resp.get("ExpenseDocuments", []):
                    for field in doc.get("SummaryFields", []):
                        if field.get("Type", {}).get("Text", "").lower() == name:
                            return field.get("ValueDetection", {}).get("Text")
                return None

            total = find_field(resp, "total")
            invoice_date = find_field(resp, "invoice_receipt_date") or find_field(resp, "invoice_date")
            vendor = find_field(resp, "vendor_name")

            result = {
                "vendor": vendor or "Unknown Vendor",
                "total": float(total) if total else None,
                "invoice_date": invoice_date,
                "billing_period": "unknown",
                "raw": resp
            }

        # save in SQLite
        s = db()
        try:
            v = s.query(Vendor).filter(Vendor.name == result["vendor"]).one_or_none()
            if not v:
                v = Vendor(name=result["vendor"])
                s.add(v)
                s.flush()
            inv = Invoice(
                vendor_id=v.id,
                total=result.get("total"),
                invoice_date=result.get("invoice_date"),
                billing_period=result.get("billing_period"),
                raw=result.get("raw"),
            )
            s.add(inv)
            s.commit()
        finally:
            s.close()

        return {"ok": True, "parsed": result}

    # Data Viewing 
    @app.get("/api/vendors")
    def get_vendors():
        s = db()
        try:
            vs = s.query(Vendor).all()
            return {"vendors": [{"id":v.id, "name":v.name} for v in vs]}
        finally:
            s.close()

    @app.get("/api/transactions")
    def list_transactions():
        vendor_id = request.args.get("vendor_id", type=int)
        limit = request.args.get("limit", default=200, type=int)

        s = SessionLocal()
        try:
            q = s.query(Transaction)
            if vendor_id is not None:
                q = q.filter(Transaction.vendor_id == vendor_id)

            items = q.order_by(Transaction.id.desc()).limit(limit).all()

            # Map vendor_id -> vendor_name safely (avoid IN () when empty)
            vendor_ids = {t.vendor_id for t in items if t.vendor_id is not None}
            vendor_map = {}
            if vendor_ids:
                rows = s.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()
                vendor_map = {v.id: v.name for v in rows}

            return {
                "transactions": [
                    {
                        "id": t.id,
                        "vendor_id": t.vendor_id,
                        "vendor_name": vendor_map.get(t.vendor_id),
                        "plaid_txn_id": t.plaid_txn_id,
                        "merchant_name": t.merchant_name,
                        "amount": t.amount,
                        "currency": t.iso_currency_code,
                        "date": t.date,
                    }
                    for t in items
                ]
            }
        finally:
            s.close()

    # Manual subscription update (not name)
    @app.patch("/api/subscriptions/<int:sub_id>")
    def update_subscription(sub_id: int):
        s = SessionLocal()
        try:
            sub = s.get(Subscription, sub_id)
            if not sub:
                return {"error": "not found"}, 404

            data = request.get_json(force=True) or {}
            status = data.get("status")
            interval = data.get("interval")
            next_expected = data.get("next_expected")  # 'YYYY-MM-DD'

            if status in {"active", "cancelled", "inferred"}:
                sub.status = status
            if interval in {"monthly", "yearly", "unknown"}:
                sub.interval = interval
            if isinstance(next_expected, str):
                sub.next_expected = next_expected

            s.commit()

            vendor = s.get(Vendor, sub.vendor_id) if sub.vendor_id else None
            return {
                "ok": True,
                "subscription": {
                    "id": sub.id,
                    "vendor": vendor.name if vendor else None,
                    "status": sub.status,
                    "interval": sub.interval,
                    "next_expected": sub.next_expected,
                }
            }
        finally:
            s.close()

    # List subscriptions
    @app.get("/api/subscriptions")
    def get_subscriptions():
        s = db()
        try:
            subs = s.query(Subscription).all()
            out = []
            for sub in subs:
                vendor = s.query(Vendor).get(sub.vendor_id) if sub.vendor_id else None
                out.append({
                    "id": sub.id,
                    "vendor": vendor.name if vendor else None,
                    "interval": sub.interval, 
                    "status": sub.status,
                    "next_expected": sub.next_expected,   
                    "confidence": getattr(sub, "confidence", None),
                })
            return {"subscriptions": out}
        finally:
            s.close()

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
