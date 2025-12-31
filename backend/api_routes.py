import json
import os
import tempfile
from datetime import date, timedelta

import boto3
from flask import current_app
from flask.views import MethodView
from flask_smorest import Blueprint
from werkzeug.utils import secure_filename

from database import SessionLocal, engine
from detection import detect_basic_subscriptions
from models import Base, Invoice, Subscription, Transaction, Vendor

from api_schemas import (
    DemoResetResponseSchema,
    ErrorResponseSchema,
    OkResponseSchema,
    PingResponseSchema,
    PlaidExchangeRequestSchema,
    PlaidLinkTokenResponseSchema,
    PlaidSandboxPublicTokenResponseSchema,
    PlaidTransactionsResponseSchema,
    SeedResponseSchema,
    SubscriptionsResponseSchema,
    TextractResponseSchema,
    TextractUploadSchema,
    TransactionsQuerySchema,
    TransactionsResponseSchema,
    UpdateSubscriptionRequestSchema,
    UpdateSubscriptionResponseSchema,
    VendorsResponseSchema,
)

# Plaid
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions


def _error(code: str, message: str, status_code: int, details=None):
    payload = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload, status_code


def _to_jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def _seed_demo_transactions(session) -> int:
    base = date.today()
    demo = [
        ("Netflix", [base, base - timedelta(days=30), base - timedelta(days=60)], 15.99),
        ("Adobe Inc.", [base - timedelta(days=5), base - timedelta(days=35), base - timedelta(days=65)], 29.99),
        ("Spotify", [base - timedelta(days=2), base - timedelta(days=32), base - timedelta(days=62)], 9.99),
        ("Starbucks", [base - timedelta(days=3), base - timedelta(days=11), base - timedelta(days=20)], 5.50),
    ]
    inserted = 0
    for name, dates, amt in demo:
        for d in dates:
            session.add(
                Transaction(
                    vendor_id=None,
                    plaid_txn_id=None,
                    merchant_name=name,
                    amount=amt,
                    iso_currency_code="USD",
                    date=d.isoformat(),
                    raw={"seed": True},
                )
            )
            inserted += 1
    return inserted


blp_core = Blueprint("core", __name__, url_prefix="/api", description="Core API")
blp_demo = Blueprint(
    "demo",
    __name__,
    url_prefix="/api/demo",
    description=(
        "Run the demo in order:\n"
        "1) POST /api/demo/reset\n"
        "2) POST /api/demo/seed\n"
        "3) POST /api/detect\n"
        "4) GET /api/subscriptions, /api/vendors, /api/transactions\n"
        "5) POST /api/textract (upload any file; MOCK_TEXTRACT=1)\n"
    ),
)
blp_plaid = Blueprint("plaid", __name__, url_prefix="/api/plaid", description="Plaid (Sandbox)")
blp_data = Blueprint("data", __name__, url_prefix="/api", description="Data viewing and editing")


@blp_core.route("/ping")
class PingResource(MethodView):
    @blp_core.response(200, PingResponseSchema)
    def get(self):
        return {"ok": True, "msg": "pong"}


@blp_demo.route("/reset")
class DemoResetResource(MethodView):
    @blp_demo.doc(summary="1) Reset demo DB")
    @blp_demo.response(200, DemoResetResponseSchema)
    def post(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        engine.dispose()
        return {"ok": True, "reset": True}


@blp_demo.route("/seed")
class DemoSeedResource(MethodView):
    @blp_demo.doc(summary="2) Seed demo transactions")
    @blp_demo.response(200, SeedResponseSchema)
    def post(self):
        s = SessionLocal()
        try:
            inserted = _seed_demo_transactions(s)
            s.commit()
            return {"ok": True, "inserted": inserted}
        finally:
            s.close()


@blp_plaid.route("/link_token")
class PlaidLinkTokenResource(MethodView):
    @blp_plaid.response(200, PlaidLinkTokenResponseSchema)
    @blp_plaid.alt_response(502, schema=ErrorResponseSchema)
    def post(self):
        plaid_client = current_app.extensions.get("plaid_client")
        if plaid_client is None:
            return _error("PLAID_NOT_CONFIGURED", "Plaid client is not configured", 500)

        try:
            req = LinkTokenCreateRequest(
                user={"client_user_id": "demo-user-123"},
                client_name="SubTracker Demo",
                products=[Products("transactions")],
                country_codes=[CountryCode("US")],
                language="en",
            )
            resp = plaid_client.link_token_create(req)
        except Exception as exc:
            return _error("PLAID_ERROR", "Plaid request failed", 502, {"detail": str(exc)})

        data = resp.to_dict()
        data["expiration"] = str(data.get("expiration"))
        return data


@blp_plaid.route("/exchange")
class PlaidExchangeResource(MethodView):
    @blp_plaid.arguments(PlaidExchangeRequestSchema)
    @blp_plaid.response(200, OkResponseSchema)
    @blp_plaid.alt_response(400, schema=ErrorResponseSchema)
    @blp_plaid.alt_response(502, schema=ErrorResponseSchema)
    def post(self, args):
        public_token = args.get("public_token")
        if not public_token:
            return _error("BAD_REQUEST", "public_token required", 400)

        plaid_client = current_app.extensions.get("plaid_client")
        if plaid_client is None:
            return _error("PLAID_NOT_CONFIGURED", "Plaid client is not configured", 500)

        try:
            ex_req = ItemPublicTokenExchangeRequest(public_token=public_token)
            ex_resp = plaid_client.item_public_token_exchange(ex_req)
        except Exception as exc:
            return _error("PLAID_ERROR", "Plaid request failed", 502, {"detail": str(exc)})

        current_app.config["PLAID_ACCESS_TOKEN"] = ex_resp.to_dict().get("access_token")
        return {"ok": True}


@blp_plaid.route("/sandbox_public_token")
class PlaidSandboxPublicTokenResource(MethodView):
    @blp_plaid.response(200, PlaidSandboxPublicTokenResponseSchema)
    @blp_plaid.alt_response(502, schema=ErrorResponseSchema)
    def post(self):
        plaid_client = current_app.extensions.get("plaid_client")
        if plaid_client is None:
            return _error("PLAID_NOT_CONFIGURED", "Plaid client is not configured", 500)

        try:
            req = SandboxPublicTokenCreateRequest(
                institution_id="ins_109509",
                initial_products=[Products("transactions")],
            )
            resp = plaid_client.sandbox_public_token_create(req)
        except Exception as exc:
            return _error("PLAID_ERROR", "Plaid request failed", 502, {"detail": str(exc)})

        return resp.to_dict()


@blp_plaid.route("/transactions")
class PlaidTransactionsResource(MethodView):
    @blp_plaid.response(200, PlaidTransactionsResponseSchema)
    @blp_plaid.alt_response(400, schema=ErrorResponseSchema)
    @blp_plaid.alt_response(502, schema=ErrorResponseSchema)
    def get(self):
        access_token = current_app.config.get("PLAID_ACCESS_TOKEN")
        if not access_token:
            return _error(
                "PLAID_NOT_LINKED",
                "Link account first (/api/plaid/link_token + /api/plaid/exchange)",
                400,
            )

        plaid_client = current_app.extensions.get("plaid_client")
        if plaid_client is None:
            return _error("PLAID_NOT_CONFIGURED", "Plaid client is not configured", 500)

        start_date = date.today() - timedelta(days=120)
        end_date = date.today()

        request_options = TransactionsGetRequestOptions(count=50)
        t_req = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=request_options,
        )

        try:
            t_resp = plaid_client.transactions_get(t_req).to_dict()
        except Exception as exc:
            return _error("PLAID_ERROR", "Plaid request failed", 502, {"detail": str(exc)})

        txns = t_resp.get("transactions", [])

        s = SessionLocal()
        saved = 0
        try:
            for t in txns:
                if s.query(Transaction).filter_by(plaid_txn_id=t.get("transaction_id")).first():
                    continue

                t_date = t.get("date")
                date_str = (
                    t_date.isoformat()
                    if hasattr(t_date, "isoformat")
                    else (str(t_date) if t_date is not None else None)
                )

                merchant = t.get("merchant_name") or t.get("name")
                obj = Transaction(
                    plaid_txn_id=t.get("transaction_id"),
                    merchant_name=merchant,
                    amount=t.get("amount"),
                    iso_currency_code=t.get("iso_currency_code"),
                    date=date_str,
                    raw=_to_jsonable(t),
                )
                s.add(obj)
                saved += 1
            s.commit()
        finally:
            s.close()

        return {"saved": saved}


@blp_core.route("/detect")
class DetectResource(MethodView):
    @blp_core.doc(summary="3) Detect subscriptions")
    @blp_core.response(200, SubscriptionsResponseSchema)
    def post(self):
        s = SessionLocal()
        try:
            detect_basic_subscriptions(s)
            subs = s.query(Subscription).all()
            out = []
            for sub in subs:
                vendor = s.get(Vendor, sub.vendor_id) if sub.vendor_id else None
                out.append(
                    {
                        "id": sub.id,
                        "vendor": vendor.name if vendor else None,
                        "interval": sub.interval,
                        "status": sub.status,
                        "next_expected": sub.next_expected,
                        "confidence": getattr(sub, "confidence", None),
                    }
                )
            return {"subscriptions": out}
        finally:
            s.close()


@blp_core.route("/seed")
class SeedResource(MethodView):
    @blp_core.response(200, SeedResponseSchema)
    def post(self):
        s = SessionLocal()
        try:
            inserted = _seed_demo_transactions(s)
            s.commit()
            return {"ok": True, "inserted": inserted}
        finally:
            s.close()


@blp_core.route("/textract")
class TextractResource(MethodView):
    @blp_core.doc(summary="5) Upload invoice (Textract mock by default)")
    @blp_core.doc(consumes=["multipart/form-data"])
    @blp_core.arguments(TextractUploadSchema, location="files")
    @blp_core.response(200, TextractResponseSchema)
    @blp_core.alt_response(400, schema=ErrorResponseSchema)
    @blp_core.alt_response(502, schema=ErrorResponseSchema)
    def post(self, files):
        file = files.get("file") if isinstance(files, dict) else None
        if not file:
            return _error("BAD_REQUEST", "file required", 400)

        filename = secure_filename(getattr(file, "filename", None) or "invoice.pdf")
        suffix = os.path.splitext(filename)[1]
        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_path = tmp.name
            file.save(temp_path)

            if os.getenv("MOCK_TEXTRACT", "0") == "1" or not os.getenv("AWS_ACCESS_KEY_ID"):
                result = {
                    "vendor": "Adobe Inc.",
                    "total": 29.99,
                    "invoice_date": "2025-07-01",
                    "billing_period": "monthly",
                    "raw": {"mock": True},
                }
            else:
                client = boto3.client("textract", region_name=os.getenv("AWS_REGION", "us-east-1"))
                with open(temp_path, "rb") as f:
                    data = f.read()
                resp = client.analyze_expense(Document={"Bytes": data})

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
                    "raw": resp,
                }
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        s = SessionLocal()
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


@blp_data.route("/vendors")
class VendorsResource(MethodView):
    @blp_data.doc(summary="4) View vendors")
    @blp_data.response(200, VendorsResponseSchema)
    def get(self):
        s = SessionLocal()
        try:
            vs = s.query(Vendor).all()
            return {"vendors": [{"id": v.id, "name": v.name} for v in vs]}
        finally:
            s.close()


@blp_data.route("/transactions")
class TransactionsResource(MethodView):
    @blp_data.doc(summary="4) View transactions")
    @blp_data.arguments(TransactionsQuerySchema, location="query")
    @blp_data.response(200, TransactionsResponseSchema)
    def get(self, args):
        vendor_id = args.get("vendor_id")
        limit = args.get("limit", 200)

        s = SessionLocal()
        try:
            q = s.query(Transaction)
            if vendor_id is not None:
                q = q.filter(Transaction.vendor_id == vendor_id)

            items = q.order_by(Transaction.id.desc()).limit(limit).all()

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


@blp_data.route("/subscriptions")
class SubscriptionsResource(MethodView):
    @blp_data.doc(summary="4) View subscriptions")
    @blp_data.response(200, SubscriptionsResponseSchema)
    def get(self):
        s = SessionLocal()
        try:
            subs = s.query(Subscription).all()
            out = []
            for sub in subs:
                vendor = s.get(Vendor, sub.vendor_id) if sub.vendor_id else None
                out.append(
                    {
                        "id": sub.id,
                        "vendor": vendor.name if vendor else None,
                        "interval": sub.interval,
                        "status": sub.status,
                        "next_expected": sub.next_expected,
                        "confidence": getattr(sub, "confidence", None),
                    }
                )
            return {"subscriptions": out}
        finally:
            s.close()


@blp_data.route("/subscriptions/<int:sub_id>")
class SubscriptionUpdateResource(MethodView):
    @blp_data.arguments(UpdateSubscriptionRequestSchema)
    @blp_data.response(200, UpdateSubscriptionResponseSchema)
    @blp_data.alt_response(404, schema=ErrorResponseSchema)
    def patch(self, args, sub_id: int):
        s = SessionLocal()
        try:
            sub = s.get(Subscription, sub_id)
            if not sub:
                return _error("NOT_FOUND", "not found", 404)

            status = args.get("status")
            interval = args.get("interval")
            next_expected = args.get("next_expected")

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
                    "confidence": getattr(sub, "confidence", None),
                },
            }
        finally:
            s.close()


def register_api(api) -> None:
    api.register_blueprint(blp_core)
    api.register_blueprint(blp_demo)
    api.register_blueprint(blp_plaid)
    api.register_blueprint(blp_data)
