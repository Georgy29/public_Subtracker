import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_smorest import Api
from plaid import ApiClient, Configuration, Environment
from plaid.api import plaid_api
from werkzeug.exceptions import HTTPException

from api_routes import register_api
from database import engine
from models import Base

load_dotenv()


def _create_plaid_client():
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    host = {
        "sandbox": Environment.Sandbox,
        "development": Environment.Development,
        "production": Environment.Production,
    }.get(env, Environment.Sandbox)

    configuration = Configuration(
        host=host,
        api_key={
            "clientId": os.getenv("PLAID_CLIENT_ID", ""),
            "secret": os.getenv("PLAID_SECRET", ""),
        },
    )
    api_client = ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)


def _error_payload(code: str, message: str, details=None) -> dict:
    payload = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")
    CORS(app)

    app.config.update(
        API_TITLE="SubTracker API",
        API_VERSION="0.1.0",
        API_DESCRIPTION=(
            "Demo run (Swagger UI):\n"
            "1) POST /api/demo/reset\n"
            "2) POST /api/demo/seed\n"
            "3) POST /api/detect\n"
            "4) GET /api/subscriptions, /api/vendors, /api/transactions\n"
            "5) POST /api/textract (upload any file; MOCK_TEXTRACT=1)\n"
        ),
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/",
        OPENAPI_SWAGGER_UI_PATH="/docs",
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
        OPENAPI_REDOC_PATH="/redoc",
        OPENAPI_REDOC_URL="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
    )

    Base.metadata.create_all(bind=engine)

    api = Api(app)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        code = (exc.name or "HTTP_ERROR").upper().replace(" ", "_")
        message = exc.description if isinstance(exc.description, str) else str(exc)

        details = None
        if hasattr(exc, "data") and exc.data:
            details = exc.data
            if isinstance(details, dict) and "messages" in details:
                details = details.get("messages")

        return jsonify(_error_payload(code, message, details)), exc.code or 500

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception):
        details = {"detail": str(exc)} if app.debug else None
        return jsonify(_error_payload("INTERNAL_SERVER_ERROR", "Unexpected error", details)), 500

    app.extensions["plaid_client"] = _create_plaid_client()

    register_api(api)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
