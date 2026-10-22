"""Процессуальные сроки по ГПК РФ.

Правила исчисления:
- ст. 107 ч. 3: срок начинает течь на следующий день после даты/события; сроки в днях — в рабочих днях;
- ст. 108 ч. 1: срок в месяцах истекает в соответствующее число последнего месяца, а если такого числа
  нет — в последний день месяца; ч. 2: если последний день нерабочий — днём окончания считается
  следующий за ним рабочий день;
- ст. 321 ч. 2: апелляционная жалоба — месяц со дня принятия решения в окончательной форме;
- ст. 209 ч. 1: решение вступает в силу по истечении срока на апелляционное обжалование;
- ст. 329 ч. 5 + ст. 376.1 ч. 1: апелляционное определение вступает в силу со дня принятия,
  кассационная жалоба — три месяца со дня вступления в силу;
- ст. 332 ч. 3: частная жалоба на определение — 15 дней со дня вынесения;
- ст. 237 ч. 1: заявление об отмене заочного решения — 7 дней со дня вручения копии.

Нерабочие дни берутся из производственного календаря, загруженного из 1С (таблица calendar_days).
Если год не загружен — запасной календарь: суббота/воскресенье и праздники по ст. 112 ТК РФ без
переносов; такой срок помечается calendar_confirmed=False.
"""
from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CalendarDay, Case, Deadline, Document

TK_HOLIDAYS = {(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8), (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)}


def fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


class WorkCalendar:
    """Календарь рабочих дней: данные 1С с запасным правилом для незагруженных лет."""

    def __init__(self, days: dict[date, bool] | None = None):
        self.days = days or {}
        self.loaded_years = {d.year for d in self.days}
        self.used_fallback = False

    @classmethod
    def from_db(cls, db: Session, years: set[int] | None = None) -> "WorkCalendar":
        q = select(CalendarDay.day, CalendarDay.working)
        rows = db.execute(q).all()
        return cls({d: w for d, w in rows if years is None or d.year in years})

    def is_working(self, d: date) -> bool:
        if d.year in self.loaded_years:
            return self.days.get(d, d.weekday() < 5)
        self.used_fallback = True
        return d.weekday() < 5 and (d.month, d.day) not in TK_HOLIDAYS

    def next_working(self, d: date) -> date:
        while not self.is_working(d):
            d += timedelta(days=1)
        return d


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


@dataclass
class Term:
    due: date
    explain: str
    confirmed: bool


def months_term(cal: WorkCalendar, start: date, months: int) -> Term:
    cal.used_fallback = False
    raw = add_months(start, months)
    due = cal.next_working(raw)
    explain = f"{months} мес. от {fmt(start)} → {fmt(raw)}"
    if due != raw:
        explain += f", нерабочий день — перенос на {fmt(due)} (ст. 108 ч. 2 ГПК)"
    return Term(due, explain, not cal.used_fallback)


def working_days_term(cal: WorkCalendar, start: date, days: int) -> Term:
    cal.used_fallback = False
    d, left = start, days
    while left:
        d += timedelta(days=1)
        if cal.is_working(d):
            left -= 1
    return Term(d, f"{days} рабочих дней от {fmt(start)} (ст. 107 ч. 3 ГПК)", not cal.used_fallback)


# --- Правила по видам актов -------------------------------------------------------------------

DECISION_TYPES = ("решение", "дополнительное решение", "заочное решение")
APPEAL_RULING = "апелляционное определение"
CASSATION_RULING = "кассационное определение"


def _is(act_type: str, *prefixes: str) -> bool:
    a = (act_type or "").casefold()
    return any(a.startswith(p) for p in prefixes)


@dataclass
class PlannedDeadline:
    kind: str
    title: str
    start: date
    term: Term
    note: str = ""


def plan_for_document(doc: Document, cal: WorkCalendar) -> list[PlannedDeadline]:
    """Какие сроки порождает акт. Возвращает пустой список, если дат недостаточно."""
    out: list[PlannedDeadline] = []
    act = doc.act_type or ""
    if _is(act, *DECISION_TYPES) and doc.instance in ("", "первая"):
        start = doc.motivated_date or doc.act_date
        if not start:
            return out
        note = "" if doc.motivated_date else "Дата изготовления мотивированного решения неизвестна — считано от даты акта; уточните."
        t = months_term(cal, start, 1)
        out.append(PlannedDeadline("appeal", "Апелляционная жалоба", start, Term(t.due, "ст. 321 ч. 2 ГПК: " + t.explain, t.confirmed), note))
        eff = t.due + timedelta(days=1)
        out.append(PlannedDeadline("effective", "Вступление в силу (если не обжаловано)", start,
                                   Term(eff, f"ст. 209 ГПК: на следующий день после окончания срока обжалования ({fmt(t.due)})", t.confirmed), note))
        delivered = (doc.meta or {}).get("delivered_date")
        if _is(act, "заочное") and delivered:
            dd = date.fromisoformat(delivered)
            t2 = working_days_term(cal, dd, 7)
            out.append(PlannedDeadline("default_cancel", "Заявление об отмене заочного решения", dd,
                                       Term(t2.due, "ст. 237 ч. 1 ГПК: 7 дней со дня вручения; " + t2.explain, t2.confirmed)))
    elif _is(act, APPEAL_RULING):
        if doc.act_date:
            t = months_term(cal, doc.act_date, 3)
            out.append(PlannedDeadline("cassation", "Кассационная жалоба", doc.act_date,
                                       Term(t.due, "ст. 376.1 ГПК (вступает в силу со дня принятия, ст. 329 ч. 5): " + t.explain, t.confirmed)))
    elif _is(act, CASSATION_RULING):
        return out
    elif _is(act, "определение") and doc.act_date:
        t = working_days_term(cal, doc.act_date, 15)
        out.append(PlannedDeadline("private_complaint", "Частная жалоба", doc.act_date,
                                   Term(t.due, "ст. 332 ч. 3 ГПК: 15 дней со дня вынесения; " + t.explain, t.confirmed)))
    return out


def recalc_case(db: Session, case: Case, cal: WorkCalendar | None = None) -> list[Deadline]:
    """Пересчитать автоматические сроки дела. Сроки, поправленные юристом (auto=False), не трогаются;
    закрытые/отменённые не воскрешаются. Возвращает изменённые/созданные сроки."""
    cal = cal or WorkCalendar.from_db(db)
    existing = {(d.document_id, d.kind): d for d in case.deadlines}
    planned_keys = set()
    changed: list[Deadline] = []
    for doc in case.documents:
        for p in plan_for_document(doc, cal):
            key = (doc.id, p.kind)
            planned_keys.add(key)
            d = existing.get(key)
            rule = p.term.explain + (f"\n{p.note}" if p.note else "")
            if d is None:
                d = Deadline(case=case, document_id=doc.id, kind=p.kind, title=p.title, start_date=p.start,
                             due_date=p.term.due, rule=rule, calendar_confirmed=p.term.confirmed, auto=True)
                db.add(d)
                changed.append(d)
            elif d.auto and (d.due_date != p.term.due or d.rule != rule or d.calendar_confirmed != p.term.confirmed):
                d.start_date, d.due_date, d.rule, d.calendar_confirmed = p.start, p.term.due, rule, p.term.confirmed
                changed.append(d)
    for key, d in existing.items():
        if d.auto and d.document_id is not None and key not in planned_keys and d.status == "open":
            d.status = "cancelled"
            d.note = (d.note + "\n" if d.note else "") + "Снят автоматически: акт больше не порождает этот срок."
            changed.append(d)
    return changed


def close_passed_events(db: Session, today: date) -> int:
    """«Вступление в силу» — не действие юриста, а событие: когда его дата прошла, срок закрывается сам
    (иначе он вечно висел бы «просроченным»). Если решение обжаловано (признак обжалования или есть акт
    апелляции), в эту дату оно в силу не вступило — срок снимается. Возвращает число закрытых сроков."""
    from .models import Event

    rows = db.scalars(select(Deadline).where(Deadline.kind == "effective", Deadline.status == "open",
                                             Deadline.due_date < today)).all()
    for d in rows:
        case = d.case
        appealed = case.appeal_flag or any((doc.instance or "") == "апелляция" for doc in case.documents)
        old = d.status
        if appealed:
            d.status = "cancelled"
            d.note = (d.note + "\n" if d.note else "") + "Решение обжаловано — в эту дату в силу не вступило."
        else:
            d.status = "done"
            d.note = (d.note + "\n" if d.note else "") + f"Вступило в силу {fmt(d.due_date)} (жалоба не поступала)."
        db.add(Event(actor_type="system", actor="system", action="deadline_updated", entity="deadline",
                     entity_id=d.id, case_id=d.case_id, data={"changes": {"status": [old, d.status]}, "auto": True}))
    return len(rows)
