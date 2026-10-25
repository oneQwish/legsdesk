"""Этап 2: поручения, уведомления, обсуждение с @упоминаниями, заседания из календаря, напоминания."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from test_api import ingest_case, obs


def as_user(name: str, role: str = "lawyer") -> TestClient:
    get_settings().dev_role = role
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", json={"login": name, "password": "dev"}).status_code == 200
    return c


def test_assignments_and_notifications(svc, lawyer):
    cid = ingest_case(svc)
    sid = as_user("sidorova")
    r = lawyer.post("/api/v1/assignments", json={"title": "Подать возражения", "assignee": "sidorova",
                                                  "due_date": str(date.today() + timedelta(days=2)), "case_id": cid})
    assert r.status_code == 201
    aid = r.json()[0]["id"]
    n = sid.get("/api/v1/notifications").json()
    assert n["unread"] == 1 and "Подать возражения" in n["items"][0]["title"]
    assert sid.patch(f"/api/v1/assignments/{aid}", json={"status": "done", "result": "подано"}).json()["status"] == "done"
    assert any("Выполнено" in x["title"] for x in lawyer.get("/api/v1/notifications").json()["items"])
    assert sid.post("/api/v1/notifications/read", json=[]).json()["marked"] == 1
    # массово: по поручению на каждое дело
    c2 = svc.post("/api/v1/ingest/cases", json=[{"uid": "U-2", "case_number": "2-2/26"}]).json()[0]["case_id"]
    r = lawyer.post("/api/v1/assignments", json={"title": "Проверить", "assignee": "sidorova", "case_ids": [cid, c2]})
    assert len(r.json()) == 2
    assert len(lawyer.get("/api/v1/assignments", params={"assignee": "sidorova"}).json()) == 2


def test_comments_mentions_and_pin(svc, lawyer, viewer):
    cid = ingest_case(svc)
    r = lawyer.post(f"/api/v1/cases/{cid}/comments", json={"text": "Посмотри акт, @viewer1 и @nobody", "pinned": True})
    assert r.status_code == 201 and r.json()["mentions"] == ["viewer1"]
    assert viewer.get("/api/v1/notifications").json()["unread"] == 1
    assert viewer.post(f"/api/v1/cases/{cid}/comments", json={"text": "x"}).status_code == 403
    lst = lawyer.get(f"/api/v1/cases/{cid}/comments").json()
    assert lst[0]["pinned"] is True
    assert lawyer.delete(f"/api/v1/comments/{lst[0]['id']}").status_code == 204


def test_hearings_snapshot_link_and_manual(svc, lawyer):
    cid = ingest_case(svc)  # номер 2-1459/2025
    items = [
        {"ext_uid": "a", "date": "2027-01-15", "time": "10:00", "court": "Железнодорожный городской суд МО",
         "case_text": "2-1459/25, беседа", "owners": ["popova"]},
        {"ext_uid": "b", "date": "2027-01-16", "case_text": "жалоба истца"},
    ]
    r = svc.post("/api/v1/ingest/hearings", json={"source": "Судебный календарь", "items": items}).json()
    assert r["created"] == 2 and r["linked"] == 1 and r["unlinked"] == 1
    hs = lawyer.get("/api/v1/hearings", params={"case_id": cid}).json()
    assert hs[0]["case_numbers"] == ["2-1459/25"] and hs[0]["link_method"] == "номер"
    other = lawyer.get("/api/v1/hearings", params={"unlinked": True}).json()[0]
    assert lawyer.post(f"/api/v1/hearings/{other['id']}/link", json={"case_id": cid}).status_code == 200
    # повтор снимка без записи «a»: она помечается removed, ручная привязка «b» сохраняется
    r = svc.post("/api/v1/ingest/hearings", json={"source": "Судебный календарь", "items": items[1:]}).json()
    assert r["removed"] == 1
    hs = lawyer.get("/api/v1/hearings", params={"case_id": cid}).json()
    assert [h["ext_uid"] for h in hs] == ["b"] and hs[0]["link_method"] == "вручную"
    again = svc.post("/api/v1/ingest/hearings", json={"source": "Судебный календарь", "items": items[1:]}).json()
    assert again["updated"] == 0 and again["created"] == 0


def test_case_number_parsing():
    from app.routers.hearings import case_numbers

    assert case_numbers("2-1459/25, беседа; апп 33-12/2026 и м-7/26") == ["2-1459/25", "33-12/2026", "М-7/26"]
    assert case_numbers("явка, направить возражения") == []


def test_reminders_once(svc, lawyer):
    from app.main import daily_upkeep

    cid = ingest_case(svc, responsible="lawyer1")
    lawyer.post(f"/api/v1/cases/{cid}/deadlines", json={"title": "Свой срок", "due_date": str(date.today() + timedelta(days=1))})
    svc.post("/api/v1/ingest/hearings", json={"source": "k", "items": [
        {"ext_uid": "h", "date": str(date.today()), "case_text": "2-1459/2025"}]})
    assert daily_upkeep() >= 2
    assert daily_upkeep() == 0  # повторно — ничего нового
    titles = [x["title"] for x in lawyer.get("/api/v1/notifications").json()["items"]]
    assert any("Свой срок" in t for t in titles) and any("Заседание сегодня" in t for t in titles)


def test_conflict_notifies_responsible(svc, lawyer):
    ingest_case(svc, responsible="lawyer1")
    obs(svc, "judge", "1С", "Иванова А.А.")
    obs(svc, "judge", "OCR", "Петрова Б.Б.")
    assert any("расходятся" in x["title"] for x in lawyer.get("/api/v1/notifications").json()["items"])
