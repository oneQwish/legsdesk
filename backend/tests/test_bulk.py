"""Массовые действия: предпросмотр, применение, журнал."""
from test_api import UID, ingest_case, obs


def test_bulk_cases_preview_and_apply(svc, lawyer, viewer):
    a = ingest_case(svc)
    b = svc.post("/api/v1/ingest/cases", json=[{"uid": "U-B", "case_number": "2-2/26", "building": "401"}]).json()[0]["case_id"]
    ids = lawyer.get("/api/v1/cases/ids").json()
    assert sorted(ids) == sorted([a, b])
    assert lawyer.get("/api/v1/cases/ids", params={"building": "401"}).json() == [b]
    r = lawyer.post("/api/v1/cases/bulk", json={"ids": ids, "action": "responsible", "value": "Sidorova"}).json()
    assert r["will_change"] == 2 and r["applied"] is False
    assert lawyer.get(f"/api/v1/cases/{a}").json()["responsible"] == ""
    r = lawyer.post("/api/v1/cases/bulk", json={"ids": ids, "action": "responsible", "value": "sidorova", "dry_run": False}).json()
    assert r["applied"] and lawyer.get(f"/api/v1/cases/{a}").json()["responsible"] == "sidorova"
    assert any(e["action"] == "case_updated" for e in lawyer.get(f"/api/v1/cases/{b}/events").json())
    assert viewer.post("/api/v1/cases/bulk", json={"ids": ids, "action": "stage", "value": "x"}).status_code == 403


def test_bulk_resolve_by_source(svc, lawyer):
    a = ingest_case(svc)
    obs(svc, "judge", "1С", "Иванова А.А.")
    obs(svc, "judge", "OCR", "Петрова Б.Б.")
    b = svc.post("/api/v1/ingest/cases", json=[{"uid": "U-B", "case_number": "2-2/26"}]).json()[0]["case_id"]
    svc.post("/api/v1/ingest/observations", json=[{"case_id": b, "field": "judge", "source": "OCR", "value": "Сидоров"},
                                                  {"case_id": b, "field": "judge", "source": "отчёт", "value": "Козлов"}])
    assert lawyer.get("/api/v1/values/sources", params={"field": "judge"}).json() == ["1С", "OCR", "отчёт"]
    r = lawyer.post("/api/v1/values/bulk-resolve", json={"ids": [a, b], "field": "judge", "source": "1С"}).json()
    assert r["disputed"] == 2 and r["will_resolve"] == 1 and r["skipped_no_source"] == 1
    r = lawyer.post("/api/v1/values/bulk-resolve", json={"ids": [a, b], "field": "judge", "source": "1С", "dry_run": False}).json()
    v = next(x for x in lawyer.get(f"/api/v1/cases/{a}").json()["values"] if x["field"] == "judge")
    assert v["status"] == "resolved" and v["value"] == "Иванова А.А." and "1С" in v["resolution_note"]
    _ = UID
