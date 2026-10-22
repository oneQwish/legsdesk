from datetime import date, timedelta

from app.deadlines import WorkCalendar, add_months, months_term, plan_for_document, working_days_term
from app.models import Document


def full_year(year: int, nonworking: set[date]) -> dict[date, bool]:
    d, out = date(year, 1, 1), {}
    while d.year == year:
        out[d] = d not in nonworking
        d += timedelta(days=1)
    return out


def test_add_months_end_of_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 10, 15), 1) == date(2026, 11, 15)


def test_month_term_moves_from_weekend():
    cal = WorkCalendar()
    # 15.11.2026 — воскресенье → 16.11.2026
    t = months_term(cal, date(2026, 10, 15), 1)
    assert t.due == date(2026, 11, 16)
    assert "перенос" in t.explain
    assert t.confirmed is False  # год не загружен из 1С — запасной календарь


def test_month_term_holiday_fallback():
    # 04.11.2026 — праздник (ст. 112 ТК) → 05.11.2026
    t = months_term(WorkCalendar(), date(2026, 10, 4), 1)
    assert t.due == date(2026, 11, 5)


def test_loaded_calendar_used_and_confirmed():
    # В «календаре 1С» 16.11.2026 сделан нерабочим (перенос) — срок уходит на 17.11
    weekends = {d for d in full_year(2026, set()) if d.weekday() >= 5}
    cal = WorkCalendar(full_year(2026, weekends | {date(2026, 11, 16)}))
    t = months_term(cal, date(2026, 10, 15), 1)
    assert t.due == date(2026, 11, 17)
    assert t.confirmed is True


def test_working_days_skip_new_year():
    # 15 рабочих дней от 25.12.2026 по запасному календарю: 28–31.12 (4), 1–8.01 праздники, 9–10.01 выходные, 11–25.01 (11)
    t = working_days_term(WorkCalendar(), date(2026, 12, 25), 15)
    assert t.due == date(2027, 1, 25)


def test_plan_decision_and_appeal_ruling():
    cal = WorkCalendar()
    dec = Document(id=1, act_type="решение", instance="первая", act_date=date(2026, 9, 1), motivated_date=date(2026, 9, 8), meta={})
    plan = {p.kind: p for p in plan_for_document(dec, cal)}
    assert plan["appeal"].term.due == date(2026, 10, 8)
    assert plan["effective"].term.due == date(2026, 10, 9)
    assert plan["appeal"].note == ""

    no_motivated = Document(id=2, act_type="решение", instance="", act_date=date(2026, 9, 1), meta={})
    assert "неизвестна" in plan_for_document(no_motivated, cal)[0].note

    app_ruling = Document(id=3, act_type="апелляционное определение", instance="апелляция", act_date=date(2026, 9, 10), meta={})
    (p,) = plan_for_document(app_ruling, cal)
    assert p.kind == "cassation" and p.term.due == date(2026, 12, 10)

    ruling = Document(id=4, act_type="определение о судебных расходах", instance="первая", act_date=date(2026, 10, 1), meta={})
    (p,) = plan_for_document(ruling, cal)
    assert p.kind == "private_complaint" and p.term.due == date(2026, 10, 22)

    default = Document(id=5, act_type="заочное решение", instance="первая", act_date=date(2026, 9, 1),
                       motivated_date=date(2026, 9, 1), meta={"delivered_date": "2026-09-14"})
    kinds = {p.kind: p.term.due for p in plan_for_document(default, cal)}
    assert kinds["default_cancel"] == date(2026, 9, 23)


def test_effective_closes_itself(svc, lawyer):
    from datetime import date, timedelta
    from app import deadlines as dl
    from app.db import SessionLocal

    def case_with_decision(uid, num, appeal):
        svc.post("/api/v1/ingest/cases", json=[{"uid": uid, "court_code": "1", "case_number": num, "appeal_flag": appeal}])
        r = svc.post("/api/v1/ingest/documents", json=[{"sha256": (uid[-1] * 64), "act_type": "решение", "instance": "первая",
                                                        "act_date": "2027-01-11", "motivated_date": "2027-01-15", "case": {"uid": uid}}])
        assert r.json()[0]["ok"], r.text

    case_with_decision("U-1", "2-1/27", False)
    case_with_decision("U-2", "2-2/27", True)
    with SessionLocal() as db:
        assert dl.close_passed_events(db, date(2027, 2, 1)) == 0  # ещё не наступило
        assert dl.close_passed_events(db, date(2027, 3, 1)) == 2
        db.commit()
    dls = {d["case_number"]: d for d in lawyer.get("/api/v1/deadlines?status=done,cancelled&kind=effective").json()}
    assert dls["2-1/27"]["status"] == "done" and dls["2-2/27"]["status"] == "cancelled"
