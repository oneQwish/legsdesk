"""Калькулятор неустойки за просрочку передачи объекта (ч. 2 ст. 6 214-ФЗ) с мораториями и штрафом.

Данные (ключевая ставка, моратории, ограничения ставки, штраф) — в backend/penalty.toml (путь —
[enforcement] penalty_file): юристы обновляют их без программиста. Расчёт по дням: каждый день периода
просрочки либо исключён мораторием, либо считается по ставке на день исполнения обязательства по договору
(с ограничением, если день попал в период ограничения). Соседние дни с одинаковыми условиями
объединяются в строки расчёта — как в иске.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

from .config import get_settings


class PenaltyConfigError(RuntimeError):
    pass


@dataclass
class Rules:
    fraction: int
    multiplier: int
    count_end_day: bool
    law: str
    rates: list[tuple[date, Decimal]]
    moratoria: list[dict]
    fine: dict
    source: str


def rules_path() -> Path:
    p = get_settings().penalty_file
    return Path(p) if p else Path(__file__).resolve().parents[1] / "penalty.toml"


@lru_cache
def load_rules() -> Rules:
    path = rules_path()
    try:
        with open(path, "rb") as f:
            d = tomllib.load(f)
    except FileNotFoundError:
        raise PenaltyConfigError(f"нет файла {path} — калькулятор неустойки недоступен") from None
    except tomllib.TOMLDecodeError as e:
        raise PenaltyConfigError(f"{path}: ошибка записи — {e}") from None
    try:
        rates = sorted((date.fromisoformat(r["from"]), Decimal(str(r["rate"]))) for r in d["key_rate"])
        moratoria = [{**m, "from": date.fromisoformat(m["from"]), "to": date.fromisoformat(m["to"]),
                      "rate_cap_value": Decimal(str(m["rate_cap_value"])) if "rate_cap_value" in m else None}
                     for m in d.get("moratorium", [])]
        p = d["penalty"]
        fine = {**d.get("fine", {}), "new_from": date.fromisoformat(d.get("fine", {}).get("new_from", "2024-09-01")),
                "no_fine_periods": [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in d.get("fine", {}).get("no_fine_periods", [])]}
        for m in moratoria:
            if m["rule"] not in ("no_accrual", "rate_cap") or (m["rule"] == "rate_cap" and m["rate_cap_value"] is None):
                raise ValueError(f"мораторий с {m['from']}: rule — no_accrual или rate_cap (с rate_cap_value)")
        return Rules(int(p.get("fraction", 300)), int(p.get("citizen_multiplier", 2)), bool(p.get("count_end_day", True)),
                     p.get("law", ""), rates, moratoria, fine, str(path))
    except (KeyError, ValueError, TypeError) as e:
        raise PenaltyConfigError(f"{path}: {e}") from None


def key_rate(rules: Rules, on: date) -> Decimal:
    rate = None
    for since, r in rules.rates:
        if since <= on:
            rate = r
    if rate is None:
        raise PenaltyConfigError(f"нет ключевой ставки на {on:%d.%m.%Y} — дополните [[key_rate]] в {rules.source}")
    return rate


@dataclass
class Segment:
    start: date
    end: date
    days: int
    rate: Decimal
    excluded: bool
    note: str
    amount: Decimal = Decimal("0")


@dataclass
class Result:
    price: Decimal
    due_date: date
    end_date: date
    base_rate: Decimal
    citizen: bool
    segments: list[Segment] = field(default_factory=list)
    days_total: int = 0
    days_counted: int = 0
    total: Decimal = Decimal("0")
    fine_percent: int | None = None
    fine: Decimal | None = None
    fine_note: str = ""
    formula: str = ""


def calculate(price: Decimal, due_date: date, end_date: date, citizen: bool = True,
              claim_deadline: date | None = None, rules: Rules | None = None) -> Result:
    """price — цена договора; due_date — последний день срока передачи по договору; end_date — день
    фактической передачи (или дата расчёта); claim_deadline — когда истёк срок добровольного удовлетворения
    претензии (для штрафа)."""
    rules = rules or load_rules()
    if end_date <= due_date:
        raise ValueError("Просрочки нет: дата передачи (расчёта) не позже последнего дня срока по договору")
    base = key_rate(rules, due_date)
    mult = rules.multiplier if citizen else 1
    res = Result(price=price, due_date=due_date, end_date=end_date, base_rate=base, citizen=citizen)
    last = end_date if rules.count_end_day else end_date - timedelta(days=1)
    day = due_date + timedelta(days=1)
    cur: Segment | None = None
    while day <= last:
        rate, excluded, note = base, False, ""
        for m in rules.moratoria:
            if m["from"] <= day <= m["to"]:
                if m["rule"] == "no_accrual":
                    excluded, note = True, f"мораторий: {m['act']}"
                elif base > m["rate_cap_value"]:
                    rate, note = m["rate_cap_value"], f"ставка не выше {m['rate_cap_value']} %: {m['act']}"
        if cur and cur.excluded == excluded and cur.rate == rate and cur.note == note:
            cur.end, cur.days = day, cur.days + 1
        else:
            cur = Segment(day, day, 1, rate, excluded, note)
            res.segments.append(cur)
        day += timedelta(days=1)
    q = Decimal("0.01")
    for s in res.segments:
        if not s.excluded:
            s.amount = (price * s.rate / Decimal(100) / rules.fraction * mult * s.days).quantize(q, ROUND_HALF_UP)
            res.days_counted += s.days
        res.days_total += s.days
    res.total = sum((s.amount for s in res.segments), Decimal("0"))
    res.formula = (f"{rules.law}: цена договора × ставка {base} % (на {due_date:%d.%m.%Y}) × 1/{rules.fraction}"
                   + (" × 2 (участник — гражданин)" if citizen and rules.multiplier == 2 else "") + " × дни просрочки")
    if claim_deadline:
        f = rules.fine
        if any(a <= claim_deadline <= b for a, b in f["no_fine_periods"]):
            res.fine_percent, res.fine, res.fine_note = 0, Decimal("0"), "срок удовлетворения претензии истёк в мораторий — штраф не взыскивается"
        else:
            pct = int(f.get("new_percent", 5)) if claim_deadline >= f["new_from"] else int(f.get("old_percent", 50))
            res.fine_percent = pct
            res.fine = (res.total * pct / Decimal(100)).quantize(q, ROUND_HALF_UP)
            res.fine_note = (f"{pct} % от неустойки ({'ч. 3 ст. 10 214-ФЗ' if pct != int(f.get('old_percent', 50)) else 'п. 6 ст. 13 ЗоЗПП'}); "
                             "суд считает штраф от всей присуждённой суммы — здесь только от неустойки")
    return res
