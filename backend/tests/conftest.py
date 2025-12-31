import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
for path in (ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import api_routes
from backend import app as app_module
from backend import database
from backend.models import Base


@pytest.fixture()
def test_app(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(api_routes, "SessionLocal", session_local)
    monkeypatch.setattr(api_routes, "engine", engine)
    monkeypatch.setattr(app_module, "engine", engine)
    monkeypatch.setenv("MOCK_TEXTRACT", "1")

    Base.metadata.create_all(bind=engine)

    app = app_module.create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture()
def client(test_app):
    return test_app.test_client()
