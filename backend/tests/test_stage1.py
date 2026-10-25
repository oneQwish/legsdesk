"""Этап 1: правка дела, заведение дела с проверкой дублей, справочники."""
from test_api import UID, ingest_case


def test_patch_any_field_and_alias(svc, lawyer, viewer):
    cid = ingest_case(svc)
    r = lawyer.patch(f"/api/v1/cases/{cid}", json={"flat": "77", "appeal_flag": True, "case_number": "2-9999/2025", "note": "по иску"})
    assert r.status_code == 200 and r.json()["flat"] == "77" and r.json()["appeal_flag"] is True
    card = lawyer.get(f"/api/v1/cases/{cid}").json()
    assert "2-9999/2025" in [a["number"] for a in card["aliases"]]
    ev = lawyer.get(f"/api/v1/cases/{cid}/events").json()[0]
    assert ev["action"] == "case_updated" and ev["data"]["note"] == "по иску"
    assert viewer.patch(f"/api/v1/cases/{cid}", json={"flat": "1"}).status_code == 403
    other = svc.post("/api/v1/ingest/cases", json=[{"uid": "77RS0001-01-2025-000001-11", "case_number": "2-1/25"}]).json()[0]["case_id"]
    assert lawyer.patch(f"/api/v1/cases/{other}", json={"uid": UID}).status_code == 409


def test_create_case_with_duplicate_check(svc, lawyer):
    cid = ingest_case(svc, building="401", flat="12", plaintiffs="Орлов А.А.")
    body = {"court_code": "000000123", "case_number": "М-500/2026", "building": "401", "flat": "12", "plaintiffs": "Орлов А. А."}
    d = lawyer.get("/api/v1/cases/duplicates", params={"building": "401", "flat": "12", "plaintiffs": "Орлов"}).json()
    assert d and d[0]["id"] == cid
    r = lawyer.post("/api/v1/cases", json=body)
    assert r.status_code == 409 and r.json()["detail"]["duplicates"][0]["id"] == cid
    r = lawyer.post("/api/v1/cases", json={**body, "force": True})
    assert r.status_code == 201 and r.json()["case_number"] == "М-500/2026"
    assert lawyer.post("/api/v1/cases", json={"court_name": "без номера"}).status_code == 400


def test_directories(svc, admin, lawyer):
    cid = svc.post("/api/v1/ingest/cases", json=[{"court_code": "555", "case_number": "2-5/26"}]).json()[0]["case_id"]
    assert admin.put("/api/v1/directories/courts/555", json={"code": "555", "name": "Энский районный суд", "short_name": "Энский райсуд"}).status_code == 200
    assert lawyer.get(f"/api/v1/cases/{cid}").json()["court_name"] == "Энский районный суд"
    facets = lawyer.get("/api/v1/cases/facets").json()["facets"]["court"]
    assert any(x["label"] == "Энский райсуд" for x in facets)
    assert lawyer.put("/api/v1/directories/courts/555", json={"code": "555", "name": "x"}).status_code == 403
    assert admin.delete("/api/v1/directories/courts/555").status_code == 409
    e = admin.post("/api/v1/directories/entities", json={"name": "ГС-Тест", "inn": "7700000000"}).json()
    svc.post("/api/v1/ingest/cases", json=[{"uid": "U-E", "case_number": "2-6/26", "legal_entity": "ГС-Тест"}])
    admin.put(f"/api/v1/directories/entities/{e['id']}", json={"name": "ГС-Тест-2"})
    assert lawyer.get("/api/v1/cases", params={"legal_entity": "ГС-Тест-2"}).json()["total"] == 1
    assert svc.post("/api/v1/ingest/courts", json=[{"code": "777", "name": "Суд-777"}]).json() == {"count": 1}
