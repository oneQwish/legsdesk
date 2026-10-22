"""Регрессии по аудиту: безопасность раздачи файлов, загрузка, вход, миграции, часовой пояс."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import clock, main
from app.config import get_settings
from app.db import engine, init_db
from app.main import app
from app.security import throttle


def upload(c, data: bytes, **meta):
    return c.post("/api/v1/ingest/documents/upload", files={"file": (meta.get("filename", "f.bin"), data)},
                  data={"meta": json.dumps(meta)})


def test_html_document_is_not_rendered_inline(svc, viewer):
    doc = upload(svc, b"<script>alert(1)</script>", filename="x.html", mime="text/html").json()["document_id"]
    r = viewer.get(f"/api/v1/documents/{doc}/file")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]
    pdf = upload(svc, b"%PDF-1.4 test", filename="a.pdf", mime="application/pdf").json()["document_id"]
    assert viewer.get(f"/api/v1/documents/{pdf}/file").headers["content-disposition"].startswith("inline")


def test_upload_size_limit(svc, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    r = upload(svc, b"x" * (1024 * 1024 + 10), filename="big.pdf")
    assert r.status_code == 413
    assert upload(svc, b"", filename="empty.pdf").status_code == 400


def test_spa_does_not_serve_files_outside_dist(tmp_path):
    if not main.DIST.exists():
        pytest.skip("фронтенд не собран")
    c = TestClient(app)
    r = c.get("/..%2f..%2f..%2f..%2f..%2f..%2fetc%2fpasswd")
    assert "root:" not in r.text
    assert c.get("/..%2fpackage.json").text.lstrip().startswith("<!doctype html>")


def test_login_throttle(monkeypatch):
    throttle._fails.clear()
    c = TestClient(app)
    for _ in range(get_settings().login_max_failures):
        assert c.post("/api/v1/auth/login", json={"login": "eve", "password": "x"}).status_code == 401
    r = c.post("/api/v1/auth/login", json={"login": "EVE", "password": "dev"})
    assert r.status_code == 429 and "мин" in r.json()["detail"]
    assert c.post("/api/v1/auth/login", json={"login": "bob", "password": "dev"}).status_code == 200
    throttle._fails.clear()


def test_health_checks_database():
    assert TestClient(app).get("/api/health").json() == {"ok": True}


def test_dangerous_settings_refuse_to_start(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "cookie_secure", True)
    with pytest.raises(RuntimeError, match="dev"):
        main.check_settings()
    monkeypatch.setattr(s, "auth_mode", "ldap")
    monkeypatch.setattr(s, "secret_key", "short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        main.check_settings()


def test_migrations_applied_once(tmp_path, monkeypatch):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE IF NOT EXISTS mig_probe (n int); INSERT INTO mig_probe VALUES (1);")
    monkeypatch.setattr("app.db.MIGRATIONS", tmp_path)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS mig_probe"))
        conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    init_db()
    init_db()  # повторный старт не выполняет файл заново
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM mig_probe")) == 1
    (tmp_path / "0002_bad.sql").write_text("ALTER TABLE nope ADD COLUMN x int;")
    with pytest.raises(RuntimeError, match="0002_bad.sql"):
        init_db()
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM schema_migrations WHERE name = '0002_bad.sql'")) == 0
        conn.execute(text("DROP TABLE mig_probe"))


def test_repo_migrations_run_on_existing_db():
    init_db()  # файлы из backend/migrations выполняются на базе, созданной create_all
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_events_unsequenced'")) == 1


def test_today_uses_company_timezone(monkeypatch):
    # 22:30 UTC — в Москве уже следующий день
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2027, 3, 1, 22, 30, tzinfo=UTC).astimezone(tz)
    monkeypatch.setattr(clock, "datetime", Fixed)
    assert clock.today().isoformat() == "2027-03-02"


def test_case_events_include_merged_history(svc, lawyer):
    a = svc.post("/api/v1/ingest/cases", json=[{"court_code": "1", "case_number": "2-1/2025"}]).json()[0]["case_id"]
    b = svc.post("/api/v1/ingest/cases", json=[{"court_code": "1", "case_number": "2-2/2025"}]).json()[0]["case_id"]
    assert lawyer.post(f"/api/v1/cases/{a}/merge/{b}").status_code == 200
    actions = [e["action"] for e in lawyer.get(f"/api/v1/cases/{a}/events").json()]
    assert actions.count("case_created") == 2 and "case_merged" in actions


def test_dev_roles_per_login(monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_roles", "petrov=viewer, sidorova=lawyer")
    monkeypatch.setattr(get_settings(), "dev_role", "admin")
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", json={"login": "Petrov", "password": "dev"}).json()["role"] == "viewer"
    assert c.post("/api/v1/auth/login", json={"login": "sidorova", "password": "dev"}).json()["role"] == "lawyer"
    assert c.post("/api/v1/auth/login", json={"login": "boss", "password": "dev"}).json()["role"] == "admin"
