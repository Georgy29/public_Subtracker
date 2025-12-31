from marshmallow import Schema, fields, validate


# (wrapped by ErrorResponseSchema).
class ErrorSchema(Schema):
    code = fields.String(required=True, metadata={"example": "BAD_REQUEST"})
    message = fields.String(required=True, metadata={"example": "Invalid request"})
    details = fields.Raw(allow_none=True)


# standard error response: { "error": { ... } }.
class ErrorResponseSchema(Schema):
    error = fields.Nested(ErrorSchema, required=True)


# Used by endpoints that return a simple success flag 
class OkResponseSchema(Schema):
    ok = fields.Boolean(required=True, metadata={"example": True})


# POST /api/demo/reset (response)
class DemoResetResponseSchema(Schema):
    ok = fields.Boolean(required=True, metadata={"example": True})
    reset = fields.Boolean(required=True, metadata={"example": True})


# GET /api/ping (response)
class PingResponseSchema(Schema):
    ok = fields.Boolean(required=True, metadata={"example": True})
    msg = fields.String(required=True, metadata={"example": "pong"})


# POST /api/plaid/exchange (request body)
class PlaidExchangeRequestSchema(Schema):
    public_token = fields.String(required=True)


# POST /api/plaid/link_token (response)
class PlaidLinkTokenResponseSchema(Schema):
    link_token = fields.String(required=True)
    expiration = fields.String(required=True)
    request_id = fields.String(required=True)


# POST /api/plaid/sandbox_public_token (response)
class PlaidSandboxPublicTokenResponseSchema(Schema):
    public_token = fields.String(required=True)
    request_id = fields.String(required=True)


# GET /api/plaid/transactions (response)
class PlaidTransactionsResponseSchema(Schema):
    saved = fields.Integer(required=True, metadata={"example": 30})


# POST /api/demo/seed and POST /api/seed (response)
class SeedResponseSchema(Schema):
    ok = fields.Boolean(required=True, metadata={"example": True})
    inserted = fields.Integer(required=True, metadata={"example": 12})


# Used inside GET /api/vendors (response)
class VendorSchema(Schema):
    id = fields.Integer(required=True, metadata={"example": 1})
    name = fields.String(required=True, metadata={"example": "Netflix"})


# GET /api/vendors (response)
class VendorsResponseSchema(Schema):
    vendors = fields.List(fields.Nested(VendorSchema), required=True)


# Used inside GET /api/transactions (response)
class TransactionSchema(Schema):
    id = fields.Integer(required=True)
    vendor_id = fields.Integer(allow_none=True)
    vendor_name = fields.String(allow_none=True)
    plaid_txn_id = fields.String(allow_none=True)
    merchant_name = fields.String(allow_none=True)
    amount = fields.Float(allow_none=True)
    currency = fields.String(allow_none=True)
    date = fields.String(allow_none=True, metadata={"example": "2025-09-08"})


# GET /api/transactions (response)
class TransactionsResponseSchema(Schema):
    transactions = fields.List(fields.Nested(TransactionSchema), required=True)


# GET /api/transactions (query params)
class TransactionsQuerySchema(Schema):
    vendor_id = fields.Integer(allow_none=True)
    limit = fields.Integer(load_default=200, validate=validate.Range(min=1, max=1000))


# Used inside GET /api/subscriptions and POST /api/detect (response)
class SubscriptionSchema(Schema):
    id = fields.Integer(required=True)
    vendor = fields.String(allow_none=True)
    interval = fields.String(allow_none=True)
    status = fields.String(required=True)
    next_expected = fields.String(allow_none=True, metadata={"example": "2025-10-01"})
    confidence = fields.Float(allow_none=True)


# GET /api/subscriptions and POST /api/detect (response)
class SubscriptionsResponseSchema(Schema):
    subscriptions = fields.List(fields.Nested(SubscriptionSchema), required=True)


# PATCH /api/subscriptions/<id> (request body)
class UpdateSubscriptionRequestSchema(Schema):
    status = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(["active", "cancelled", "inferred"]),
    )
    interval = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(["monthly", "yearly", "unknown"]),
    )
    next_expected = fields.String(load_default=None, allow_none=True)


# PATCH /api/subscriptions/<id> (response)
class UpdateSubscriptionResponseSchema(Schema):
    ok = fields.Boolean(required=True)
    subscription = fields.Nested(SubscriptionSchema, required=True)


# POST /api/textract (multipart/form-data request)
class TextractUploadSchema(Schema):
    file = fields.Raw(
        required=True,
        metadata={
            "description": "PDF/image file",
            "type": "string",
            "format": "binary",
        },
    )


# Used inside POST /api/textract (response)
class ParsedInvoiceSchema(Schema):
    vendor = fields.String(required=True)
    total = fields.Float(allow_none=True)
    invoice_date = fields.String(allow_none=True)
    billing_period = fields.String(allow_none=True)
    raw = fields.Raw(allow_none=True)


# POST /api/textract (response)
class TextractResponseSchema(Schema):
    ok = fields.Boolean(required=True)
    parsed = fields.Nested(ParsedInvoiceSchema, required=True)
