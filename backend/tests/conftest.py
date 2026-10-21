import os
import tempfile

os.environ.setdefault("LAWDESK_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5433/lawdesk_test")
os.environ["LAWDESK_AUTH_MODE"] = "dev"
os.environ["LAWDESK_STORAGE_DIR"] = tempfile.mkdtemp(prefix="lawdesk-store-")

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Service
from app.security import issue_api_key


@pytest.fixture(autouse=True)
def clean_db():
    from app import models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def login(role: str) -> TestClient:
    get_settings().dev_role = role
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"login": f"{role}1", "password": "dev"})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def lawyer() -> TestClient:
    return login("lawyer")


@pytest.fixture
def viewer() -> TestClient:
    return login("viewer")


@pytest.fixture
def admin() -> TestClient:
    return login("admin")


def make_service(name="ocr", scopes=("read", "ingest", "tasks", "export", "calendar"), task_types=()) -> TestClient:
    with SessionLocal() as db:
        s = Service(name=name, scopes=list(scopes), task_types=list(task_types))
        db.add(s)
        db.flush()
        key = issue_api_key(db, s)
        db.commit()
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {key}"
    return c


@pytest.fixture
def svc() -> TestClient:
    return make_service()
