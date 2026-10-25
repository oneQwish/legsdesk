"""Калькулятор неустойки 214-ФЗ: ставка на день исполнения, моратории, ограничение ставки, штраф."""
from datetime import date
from decimal import Decimal

from app.penalty import calculate, load_rules


def test_simple_no_moratorium():
    # 1 000 000 × 16 % (ставка на 31.01.2026) / 300 × 2 × 10 дней = 10 666.67
    r = calculate(Decimal("1000000"), date(2026, 1, 31), date(2026, 2, 10))
    assert r.base_rate == Decimal("16.0") and r.days_counted == 10 and r.total == Decimal("10666.67")
    assert calculate(Decimal("1000000"), date(2026, 1, 31), date(2026, 2, 10), citizen=False).total == Decimal("5333.33")


def test_moratorium_and_rate_cap():
    # срок 30.06.2023, передача 31.03.2024: 01.07.2023–21.03.2024 по ставке min(7.5, ставка на 30.06.2023 = 7.5);
    # с 22.03.2024 — мораторий
    r = calculate(Decimal("3000000"), date(2023, 6, 30), date(2024, 3, 31))
    counted = [s for s in r.segments if not s.excluded]
    excluded = [s for s in r.segments if s.excluded]
    assert counted[0].start == date(2023, 7, 1) and counted[-1].end == date(2024, 3, 21)
    assert excluded[0].start == date(2024, 3, 22) and excluded[-1].end == date(2024, 3, 31)
    assert all(s.rate == Decimal("7.5") for s in counted)
    assert r.days_counted == 265


def test_rate_cap_applies_when_base_higher():
    # срок 31.12.2023 (ставка 16 %), период январь 2024 — ограничение 7.5 %
    r = calculate(Decimal("1000000"), date(2023, 12, 31), date(2024, 1, 31))
    assert r.base_rate == Decimal("16.0") and r.segments[0].rate == Decimal("7.5") and "326" in r.segments[0].note


def test_fine_regimes():
    r = calculate(Decimal("1000000"), date(2026, 1, 31), date(2026, 2, 10), claim_deadline=date(2026, 3, 1))
    assert r.fine_percent == 5
    r = calculate(Decimal("1000000"), date(2026, 1, 31), date(2026, 2, 10), claim_deadline=date(2021, 3, 1))
    assert r.fine_percent == 50
    r = calculate(Decimal("1000000"), date(2026, 1, 31), date(2026, 2, 10), claim_deadline=date(2024, 6, 1))
    assert r.fine_percent == 0


def test_rules_file_valid():
    rules = load_rules()
    assert rules.rates[0][0] < date(2020, 4, 3) and rules.fraction == 300


def test_api(svc, lawyer):
    from test_api import ingest_case, obs

    cid = ingest_case(svc)
    obs(svc, "contract_price", "1С", "1 000 000")
    obs(svc, "transfer_due", "1С", "31.01.2026")
    obs(svc, "amount_penalty", "1С", "5000")
    d = lawyer.get(f"/api/v1/cases/{cid}/penalty").json()
    assert d["price"] == 1000000 and d["due_date"] == "2026-01-31" and d["result"]["total"] > 0 and d["awarded_penalty"] == 5000
    r = lawyer.post("/api/v1/penalty/calc", json={"price": 1000000, "due_date": "2026-01-31", "end_date": "2026-02-10"}).json()
    assert r["total"] == 10666.67
    assert lawyer.post("/api/v1/penalty/calc", json={"price": 1, "due_date": "2026-02-10", "end_date": "2026-02-01"}).status_code == 400
