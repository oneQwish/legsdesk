import hashlib
from datetime import date, timedelta

from conftest import make_service

UID = "50RS0010-01-2025-000287-27"


def ingest_case(svc, **kw):
    body = {"uid": UID, "court_code": "000000123", "court_name": "Железнодорожный городской суд МО",
            "case_number": "2-1459/2025", "aliases": ["М-257/2025"], "legal_entity": "ГС-Саввино", **kw}
    r = svc.post("/api/v1/ingest/cases", json=[body])
    assert r.status_code == 200 and r.json()[0]["ok"], r.text
    return r.json()[0]["case_id"]


def obs(svc, field, source, value, **kw):
    r = svc.post("/api/v1/ingest/observations", json=[{"uid": UID, "field": field, "source": source, "value": value, **kw}])
    assert r.json()[0]["ok"], r.text
    return r.json()[0]


def test_case_upsert_by_uid_and_alias(svc):
    cid = ingest_case(svc)
    # Тот же дело по М-номеру без УИД — не дубль
    r = svc.post("/api/v1/ingest/cases", json=[{"court_code": "000000123", "case_number": "М-257/2025", "building": "401"}])
    assert r.json()[0]["case_id"] == cid and r.json()[0]["created"] is False
    # Другой УИД для того же дела — предупреждение, УИД не перезаписан
    r = svc.post("/api/v1/ingest/cases", json=[{"uid": "50RS0010-01-2025-999999-99", "court_code": "000000123", "case_number": "2-1459/2025"}])
    assert r.json()[0]["created"] is True  # новый УИД — новое дело (номер уже занят → предупреждение)
    assert any("уже принадлежит" in w for w in r.json()[0]["warnings"])
    # Ошибка одного элемента пакета не мешает остальным
    r = svc.post("/api/v1/ingest/cases", json=[{"court_name": "без ключа"}, {"uid": UID}])
    assert [x["ok"] for x in r.json()] == [False, True]


def test_conflict_resolve_reopen_export_feed(svc, lawyer, viewer):
    cid = ingest_case(svc)
    assert obs(svc, "amount_debt", "1С", "141 611,96")["status"] == "single"
    assert obs(svc, "amount_debt", "письмо", "141611.96 руб.", source_ref="80215024441395")["status"] == "confirmed"
    assert obs(svc, "amount_debt", "отчёт", "283223.92")["status"] == "conflict"
    # повтор того же наблюдения — без дубля
    obs(svc, "amount_debt", "отчёт", "283223.92")

    card = lawyer.get(f"/api/v1/cases/{cid}").json()
    (v,) = [x for x in card["values"] if x["field"] == "amount_debt"]
    assert v["status"] == "conflict" and len(v["observations"]) == 3 and v["label"] == "Основной долг"
    assert card["conflicts"] == 1

    q = viewer.get("/api/v1/conflicts").json()
    assert q["total"] == 1

    # viewer не может решать
    assert viewer.post(f"/api/v1/values/{v['id']}/resolve", json={"value": "1"}).status_code == 403
    # своё значение без комментария нельзя
    assert lawyer.post(f"/api/v1/values/{v['id']}/resolve", json={"value": "141611.96"}).status_code == 400
    letter = next(o for o in v["observations"] if o["source"] == "письмо")
    r = lawyer.post(f"/api/v1/values/{v['id']}/resolve", json={"observation_id": letter["id"], "note": "в отчёте сумма на двух истцов"})
    assert r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["value"] == "141611.96 руб."
    assert lawyer.get("/api/v1/conflicts").json()["total"] == 0

    # повтор уже известного значения конфликт не открывает, новое — открывает
    obs(svc, "amount_debt", "OCR", "283 223,92")
    assert obs(svc, "amount_debt", "OCR", "141 611,96")["status"] == "resolved"
    assert obs(svc, "amount_debt", "OCR", "100000")["status"] == "conflict"

    # лента изменений: решение юриста попадает, курсор работает
    feed = svc.get("/api/v1/changes", params={"actions": "value_resolved"}).json()
    assert [e["action"] for e in feed["items"]] == ["value_resolved"]
    assert feed["items"][0]["data"]["note"] == "в отчёте сумма на двух истцов"
    again = svc.get("/api/v1/changes", params={"after": feed["next_cursor"], "actions": "value_resolved"}).json()
    assert again["items"] == [] and again["next_cursor"] >= feed["next_cursor"]

    # выгрузка: решённое снова в конфликте → в выгрузку решений не попадает; разрешим заново
    v2 = lawyer.get(f"/api/v1/cases/{cid}").json()["values"][0]
    lawyer.post(f"/api/v1/values/{v2['id']}/resolve", json={"value": "141611.96", "note": "по цифровому оригиналу"})
    csv = lawyer.get("/api/v1/export/values", params={"format": "csv"})
    assert csv.status_code == 200
    text = csv.content.decode("utf-8-sig")
    assert UID in text and "141611.96" in text and "решено юристом" in text
    xlsx = lawyer.get("/api/v1/export/values")
    assert xlsx.content[:2] == b"PK"


def test_text_normalization_confirms(svc):
    ingest_case(svc)
    obs(svc, "judge", "1С", "Пономарёва  Е.В.")
    assert obs(svc, "judge", "OCR", "пономарева е.в.")["status"] == "confirmed"
    obs(svc, "plaintiffs", "1С", "Иванов И.И.; Петрова А.А.")
    assert obs(svc, "plaintiffs", "письмо", "Петрова А.А.; Иванов И.И.")["status"] == "confirmed"


def test_documents_deadlines_and_manual_edit(svc, lawyer):
    cid = ingest_case(svc)
    sha = "a" * 64
    r = svc.post("/api/v1/ingest/documents", json=[{"sha256": sha, "filename": "решение.pdf", "kind": "письмо",
                                                    "act_type": "решение", "instance": "первая", "act_date": "2026-09-01",
                                                    "motivated_date": "2026-09-08", "case": {"uid": UID}}])
    assert r.json()[0]["case_id"] == cid
    dls = {d["kind"]: d for d in lawyer.get(f"/api/v1/cases/{cid}").json()["deadlines"]}
    assert dls["appeal"]["due_date"] == "2026-10-08" and dls["effective"]["due_date"] == "2026-10-09"
    assert dls["appeal"]["calendar_confirmed"] is False

    # загрузка календаря из 1С: 08.10.2026 объявлен нерабочим → апелляция переносится
    weekends = [date(2026, 1, 1) + timedelta(days=i) for i in range(365) if (date(2026, 1, 1) + timedelta(days=i)).weekday() >= 5]
    holidays = [date(2026, 1, d) for d in range(1, 9)] + [date(2026, 2, 23), date(2026, 3, 9), date(2026, 5, 1),
                                                          date(2026, 5, 11), date(2026, 6, 12), date(2026, 11, 4), date(2026, 10, 8)]
    r = svc.put("/api/v1/calendar", json={"year": 2026, "nonworking": [d.isoformat() for d in set(weekends + holidays)]})
    assert r.status_code == 200, r.text
    assert r.json()["deadlines_changed"] >= 1
    dls = {d["kind"]: d for d in lawyer.get(f"/api/v1/cases/{cid}").json()["deadlines"]}
    assert dls["appeal"]["due_date"] == "2026-10-09" and dls["appeal"]["calendar_confirmed"] is True

    # ручная правка даты — пересчёт её не трогает
    lawyer.patch(f"/api/v1/deadlines/{dls['appeal']['id']}", json={"due_date": "2026-10-20"})
    lawyer.post(f"/api/v1/cases/{cid}/deadlines/recalc")
    dls = {d["kind"]: d for d in lawyer.get(f"/api/v1/cases/{cid}").json()["deadlines"]}
    assert dls["appeal"]["due_date"] == "2026-10-20" and dls["appeal"]["auto"] is False

    # апелляционное определение → кассация
    svc.post("/api/v1/ingest/documents", json=[{"sha256": "b" * 64, "act_type": "апелляционное определение",
                                                "instance": "апелляция", "act_date": "2026-12-10", "case": {"case_number": "33-100/2026", "court_code": "000000123"}}])
    # номер 33- не известен → документ не привязан, ссылка сохранена
    doc = lawyer.get("/api/v1/documents", params={"unlinked": True}).json()["items"][0]
    assert doc["case_id"] is None
    lawyer.post(f"/api/v1/documents/{doc['id']}/link", json={"case_id": cid})
    kinds = {d["kind"]: d for d in lawyer.get(f"/api/v1/cases/{cid}").json()["deadlines"]}
    assert kinds["cassation"]["due_date"] == "2027-03-10"

    upcoming = lawyer.get("/api/v1/deadlines", params={"due_before": "2027-12-31"}).json()
    assert {d["kind"] for d in upcoming} >= {"appeal", "cassation"} and upcoming[0]["case_number"] == "2-1459/2025"


def test_upload_and_download(svc, lawyer, viewer):
    cid = ingest_case(svc)
    pdf = b"%PDF-1.4 test"
    r = svc.post("/api/v1/ingest/documents/upload",
                 files={"file": ("скан.pdf", pdf, "application/pdf"), "signature": ("x.sig", b"SIG", "application/octet-stream")},
                 data={"meta": '{"kind": "письмо", "act_type": "решение", "case": {"uid": "%s"}}' % UID})
    assert r.status_code == 200, r.text
    did = r.json()["document_id"]
    assert r.json()["case_id"] == cid
    f = viewer.get(f"/api/v1/documents/{did}/file")
    assert f.content == pdf
    assert viewer.get(f"/api/v1/documents/{did}/file", params={"signature": True}).content == b"SIG"
    d = viewer.get(f"/api/v1/documents/{did}").json()
    assert d["sha256"] == hashlib.sha256(pdf).hexdigest() and d["storage_backend"] == "local"
    # повторная загрузка — тот же документ
    r2 = svc.post("/api/v1/ingest/documents/upload", files={"file": ("копия.pdf", pdf)})
    assert r2.json()["document_id"] == did and r2.json()["created"] is False


def test_tasks_queue():
    a = make_service("ocr-1", task_types=["ocr"])
    b = make_service("ocr-2", task_types=["ocr"])
    for i in range(3):
        a.post("/api/v1/tasks", json={"type": "ocr", "payload": {"n": i}, "max_attempts": 2})
    ta = a.post("/api/v1/tasks/claim", json={"limit": 2}).json()
    tb = b.post("/api/v1/tasks/claim", json={"limit": 5}).json()
    assert len(ta) == 2 and len(tb) == 1
    assert not {t["id"] for t in ta} & {t["id"] for t in tb}
    # чужую задачу завершить нельзя
    assert b.post(f"/api/v1/tasks/{ta[0]['id']}/complete", json={}).status_code == 409
    assert a.post(f"/api/v1/tasks/{ta[0]['id']}/complete", json={"result": {"pages": 3}}).json()["status"] == "done"
    r = a.post(f"/api/v1/tasks/{ta[1]['id']}/fail", json={"error": "timeout", "retry_in_seconds": 0}).json()
    assert r["status"] == "queued"
    again = b.post("/api/v1/tasks/claim", json={}).json()
    assert [t["id"] for t in again] == [ta[1]["id"]] and again[0]["attempts"] == 2
    r = b.post(f"/api/v1/tasks/{ta[1]['id']}/fail", json={"error": "timeout"}).json()
    assert r["status"] == "failed"  # попытки исчерпаны
    # истёкшая аренда — задача доступна другому
    b.post(f"/api/v1/tasks/{tb[0]['id']}/heartbeat", json={"lease_seconds": 30})
    from app.db import SessionLocal
    from app.models import Task
    from sqlalchemy import update, func, text
    with SessionLocal() as db:
        db.execute(update(Task).where(Task.id == tb[0]["id"]).values(lease_until=func.now() - text("interval '1 minute'")))
        db.commit()
    stolen = a.post("/api/v1/tasks/claim", json={}).json()
    assert [t["id"] for t in stolen] == [tb[0]["id"]]


def test_permissions(viewer, admin, lawyer):
    limited = make_service("reader", scopes=["read"])
    assert limited.post("/api/v1/ingest/cases", json=[]).status_code == 403
    assert limited.get("/api/v1/cases").status_code == 200
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    assert anon.get("/api/v1/cases").status_code == 401
    bad = TestClient(app)
    bad.headers["X-API-Key"] = "ldk_deadbeef_nope"
    assert bad.get("/api/v1/cases").status_code == 401
    assert lawyer.get("/api/v1/admin/services").status_code == 403

    s = admin.post("/api/v1/admin/services", json={"name": "letters", "scopes": ["ingest", "read"]}).json()
    key = admin.post(f"/api/v1/admin/services/{s['id']}/keys").json()["key"]
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {key}"
    assert c.get("/api/v1/cases").status_code == 200
    kid = admin.get("/api/v1/admin/services").json()[0]["keys"][0]["id"]
    admin.delete(f"/api/v1/admin/keys/{kid}")
    assert c.get("/api/v1/cases").status_code == 401
    assert admin.post("/api/v1/admin/services", json={"name": "x", "scopes": ["root"]}).status_code == 400


def test_merge_cases(svc, lawyer):
    a = ingest_case(svc)
    r = svc.post("/api/v1/ingest/cases", json=[{"court_code": "000000123", "case_number": "2-4522/2024"}])
    b = r.json()[0]["case_id"]
    svc.post("/api/v1/ingest/observations", json=[{"case_id": b, "field": "judge", "source": "1С", "value": "Иванова"}])
    obs(svc, "judge", "OCR", "Петрова")
    lawyer.post(f"/api/v1/cases/{a}/merge/{b}")
    card = lawyer.get(f"/api/v1/cases/{a}").json()
    assert {x["number"] for x in card["aliases"]} == {"2-1459/2025", "М-257/2025", "2-4522/2024"}
    (j,) = [v for v in card["values"] if v["field"] == "judge"]
    assert j["status"] == "conflict" and len(j["observations"]) == 2
    assert lawyer.get(f"/api/v1/cases/{b}").status_code == 404
    found = lawyer.get("/api/v1/cases", params={"q": "4522"}).json()
    assert found["total"] == 1 and found["items"][0]["id"] == a
