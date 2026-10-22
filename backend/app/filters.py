"""Фильтры по делам — общие для реестра дел, очереди конфликтов и сроков.

Каждый фильтр — отдельное условие на Case с ключом-фасетом. Для подсчёта значений фасета
(«сколько дел останется, если отметить») применяются все условия, кроме условия самого фасета —
так счётчики не обнуляются после выбора одного значения (как в интернет-магазинах).
Условия на связанные таблицы — через EXISTS, поэтому строки дел не размножаются.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Query
from sqlalchemy import Date, Numeric, and_, case as sa_case, cast, func, literal, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from . import clock
from .fields import FIELDS
from .logic import search_cases_filter
from .models import Case, CaseValue, Deadline, Document, Observation

DISPUTED = ("conflict", "appeal_possible")
NONE = "—"  # значение фасета «не указано»

next_due_sq = (select(func.min(Deadline.due_date)).where(Deadline.case_id == Case.id, Deadline.status == "open")
               .correlate(Case).scalar_subquery())

# Год дела — из номера «2-1459/2025» или «2-6637/23»
_year_raw = func.substring(Case.case_number, r"/(\d{2,4})$")
case_year = sa_case(
    (func.length(_year_raw) == 2, literal("20").concat(_year_raw)),
    (func.length(_year_raw) == 4, _year_raw),
    else_=literal(NONE),
)


# Подзапросы EXISTS — на отдельных псевдонимах таблиц и с явной корреляцией только с делом:
# иначе при подсчёте фасета, где та же таблица присоединена снаружи, подзапрос теряет FROM.
_cv, _dl, _doc = aliased(CaseValue), aliased(Deadline), aliased(Document)
_jcv, _job = aliased(CaseValue), aliased(Observation)  # судья: поле + наблюдения источников


def _ex(alias, *conds):
    return select(literal(1)).select_from(alias).where(*conds).correlate(Case).exists()


def money(col):
    """Число из текста суммы: «141 611,96 руб.» → 141611.96 (NULL, если цифр нет)."""
    digits = func.substring(func.regexp_replace(col, r"\s", "", "g"), r"^-?[0-9]+(?:[.,][0-9]{1,2})?")
    return cast(func.replace(digits, ",", "."), Numeric(18, 2))


@dataclass
class CaseFilter:
    """Все фильтры по делу. Списочные параметры повторяются: ?building=401&building=308."""

    q: str = ""
    legal_entity: list[str] | None = None
    complex: list[str] | None = None
    building: list[str] | None = None
    court: list[str] | None = None          # код суда 1С
    year: list[str] | None = None
    stage: list[str] | None = None
    status: list[str] | None = None
    outcome: list[str] | None = None
    subject: list[str] | None = None
    responsible: list[str] | None = None    # «—» — не назначен
    conflict_field: list[str] | None = None  # есть конфликт по полю
    deadline_kind: list[str] | None = None  # есть открытый срок вида
    act_type: list[str] | None = None       # есть документ вида
    judge: list[str] | None = None          # судья по любому источнику (приведённое написание)
    has_uid: bool | None = None
    has_conflicts: bool | None = None
    appeal_flag: bool | None = None
    has_documents: bool | None = None
    overdue: bool | None = None
    due_from: date | None = None
    due_to: date | None = None
    decision_from: date | None = None
    decision_to: date | None = None
    updated_from: date | None = None
    updated_to: date | None = None
    sum_field: str | None = None
    sum_min: float | None = None
    sum_max: float | None = None

    @classmethod
    def dep(
        cls,
        q: str = "",
        legal_entity: list[str] | None = Query(None),
        complex: list[str] | None = Query(None),
        building: list[str] | None = Query(None),
        court: list[str] | None = Query(None),
        year: list[str] | None = Query(None),
        stage: list[str] | None = Query(None),
        status: list[str] | None = Query(None, alias="case_status"),
        outcome: list[str] | None = Query(None),
        subject: list[str] | None = Query(None),
        responsible: list[str] | None = Query(None),
        conflict_field: list[str] | None = Query(None),
        deadline_kind: list[str] | None = Query(None),
        act_type: list[str] | None = Query(None),
        judge: list[str] | None = Query(None),
        has_uid: bool | None = None,
        has_conflicts: bool | None = None,
        appeal_flag: bool | None = None,
        has_documents: bool | None = None,
        overdue: bool | None = None,
        due_from: date | None = None,
        due_to: date | None = Query(None, alias="due_before"),
        decision_from: date | None = None,
        decision_to: date | None = None,
        updated_from: date | None = None,
        updated_to: date | None = None,
        sum_field: str | None = None,
        sum_min: float | None = None,
        sum_max: float | None = None,
    ) -> "CaseFilter":
        return cls(**{k: v for k, v in locals().items() if k != "cls"})

    def conditions(self) -> dict[str, ColumnElement[bool]]:
        """{фасет: условие}. Фасеты без выбранных значений в словарь не попадают."""
        c: dict[str, ColumnElement[bool]] = {}

        def multi(key: str, col, values: list[str] | None):
            if values:
                real = [v for v in values if v != NONE]
                parts = [col.in_(real)] if real else []
                if NONE in values:
                    parts.append(or_(col.is_(None), col == ""))
                c[key] = or_(*parts)

        if self.q.strip():
            c["q"] = search_cases_filter(self.q)
        multi("legal_entity", Case.legal_entity, self.legal_entity)
        multi("complex", Case.complex, self.complex)
        multi("building", Case.building, self.building)
        multi("court", Case.court_code, self.court)
        multi("stage", Case.stage, self.stage)
        multi("status", Case.status, self.status)
        multi("outcome", Case.outcome, self.outcome)
        multi("subject", Case.subject, self.subject)
        multi("responsible", Case.responsible, self.responsible)
        if self.year:
            c["year"] = case_year.in_(self.year)
        if self.conflict_field:
            c["conflict_field"] = _ex(_cv, _cv.case_id == Case.id, _cv.status.in_(DISPUTED), _cv.field.in_(self.conflict_field))
        if self.deadline_kind:
            c["deadline_kind"] = _ex(_dl, _dl.case_id == Case.id, _dl.status == "open", _dl.kind.in_(self.deadline_kind))
        if self.judge:
            # дело подходит, если хоть один источник называет этого судью (так находятся и дела со спорным судьёй)
            c["judge"] = (select(literal(1)).select_from(_jcv).join(_job, _job.case_value_id == _jcv.id)
                          .where(_jcv.case_id == Case.id, _jcv.field == "judge", _job.normalized.in_(self.judge))
                          .correlate(Case).exists())
        if self.act_type:
            c["act_type"] = _ex(_doc, _doc.case_id == Case.id, _doc.act_type.in_(self.act_type))
        if self.has_uid is not None:
            c["has_uid"] = Case.uid.is_not(None) if self.has_uid else Case.uid.is_(None)
        if self.has_conflicts is not None:
            e = _ex(_cv, _cv.case_id == Case.id, _cv.status.in_(DISPUTED))
            c["has_conflicts"] = e if self.has_conflicts else ~e
        if self.appeal_flag is not None:
            c["appeal_flag"] = Case.appeal_flag.is_(self.appeal_flag)
        if self.has_documents is not None:
            e = _ex(_doc, _doc.case_id == Case.id)
            c["has_documents"] = e if self.has_documents else ~e
        if self.overdue:
            c["overdue"] = _ex(_dl, _dl.case_id == Case.id, _dl.status == "open", _dl.due_date < clock.today())
        if self.due_from or self.due_to:
            parts = []
            if self.due_from:
                parts.append(next_due_sq >= self.due_from)
            if self.due_to:
                parts.append(next_due_sq <= self.due_to)
            c["due"] = and_(*parts)
        if self.decision_from or self.decision_to:
            cond = [_doc.case_id == Case.id, _doc.act_type.ilike("%решение%")]
            if self.decision_from:
                cond.append(_doc.act_date >= self.decision_from)
            if self.decision_to:
                cond.append(_doc.act_date <= self.decision_to)
            c["decision"] = _ex(_doc, *cond)
        if self.updated_from:
            c["updated_from"] = cast(Case.updated_at, Date) >= self.updated_from
        if self.updated_to:
            c["updated_to"] = cast(Case.updated_at, Date) <= self.updated_to
        if self.sum_field and (self.sum_min is not None or self.sum_max is not None):
            num = money(_cv.value)
            cond = [_cv.case_id == Case.id, _cv.field == self.sum_field, _cv.status.notin_(DISPUTED)]
            if self.sum_min is not None:
                cond.append(num >= self.sum_min)
            if self.sum_max is not None:
                cond.append(num <= self.sum_max)
            c["sum"] = _ex(_cv, *cond)
        return c

    def where(self, exclude: str | None = None) -> list[ColumnElement[bool]]:
        return [v for k, v in self.conditions().items() if k != exclude]


# --- Фасеты: значения с числом дел ------------------------------------------------------------

SIMPLE_FACETS = {
    "legal_entity": Case.legal_entity,
    "complex": Case.complex,
    "building": Case.building,
    "stage": Case.stage,
    "status": Case.status,
    "outcome": Case.outcome,
    "subject": Case.subject,
    "responsible": Case.responsible,
}

DEADLINE_KIND_LABEL = {
    "appeal": "апелляционная жалоба", "effective": "вступление в силу", "cassation": "кассационная жалоба",
    "private_complaint": "частная жалоба", "default_cancel": "отмена заочного", "hearing": "заседание", "custom": "свой срок",
}


def facet_counts(db, f: CaseFilter, limit: int = 200) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}

    def run(key: str, stmt, label=None):
        rows = db.execute(stmt.where(*f.where(exclude=key)).group_by(stmt.selected_columns[0])
                          .order_by(func.count(func.distinct(Case.id)).desc()).limit(limit)).all()
        out[key] = [{"value": (r[0] if r[0] not in (None, "") else NONE),
                     "label": label(r) if label else (r[0] if r[0] not in (None, "") else "не указано"),
                     "count": r[-1]} for r in rows]

    for key, col in SIMPLE_FACETS.items():
        run(key, select(col, func.count(func.distinct(Case.id))).select_from(Case))
    run("court", select(Case.court_code, func.max(Case.court_name), func.count(func.distinct(Case.id))).select_from(Case),
        label=lambda r: r[1] or r[0] or "не указан")
    run("year", select(case_year, func.count(func.distinct(Case.id))).select_from(Case))
    run("conflict_field", select(CaseValue.field, func.count(func.distinct(Case.id))).select_from(Case)
        .join(CaseValue, and_(CaseValue.case_id == Case.id, CaseValue.status.in_(DISPUTED))),
        label=lambda r: FIELDS[r[0]].label if r[0] in FIELDS else r[0])
    run("deadline_kind", select(Deadline.kind, func.count(func.distinct(Case.id))).select_from(Case)
        .join(Deadline, and_(Deadline.case_id == Case.id, Deadline.status == "open")),
        label=lambda r: DEADLINE_KIND_LABEL.get(r[0], r[0]))
    run("act_type", select(Document.act_type, func.count(func.distinct(Case.id))).select_from(Case)
        .join(Document, Document.case_id == Case.id))
    run("judge", select(Observation.normalized, func.max(Observation.value), func.count(func.distinct(Case.id))).select_from(Case)
        .join(CaseValue, and_(CaseValue.case_id == Case.id, CaseValue.field == "judge"))
        .join(Observation, and_(Observation.case_value_id == CaseValue.id, Observation.normalized != "")),
        label=lambda r: r[1])
    out["year"].sort(key=lambda x: x["value"], reverse=True)
    return out


def flags(db, f: CaseFilter) -> dict[str, dict[str, int]]:
    """Числа для переключателей «да/нет» (с учётом остальных фильтров)."""
    def count(key: str, cond) -> int:
        return db.scalar(select(func.count(Case.id)).where(cond, *f.where(exclude=key))) or 0

    conf = _ex(_cv, _cv.case_id == Case.id, _cv.status.in_(DISPUTED))
    docs = _ex(_doc, _doc.case_id == Case.id)
    od = _ex(_dl, _dl.case_id == Case.id, _dl.status == "open", _dl.due_date < clock.today())
    return {
        "has_uid": {"true": count("has_uid", Case.uid.is_not(None)), "false": count("has_uid", Case.uid.is_(None))},
        "has_conflicts": {"true": count("has_conflicts", conf), "false": count("has_conflicts", ~conf)},
        "appeal_flag": {"true": count("appeal_flag", Case.appeal_flag.is_(True)), "false": count("appeal_flag", Case.appeal_flag.is_(False))},
        "has_documents": {"true": count("has_documents", docs), "false": count("has_documents", ~docs)},
        "overdue": {"true": count("overdue", od)},
    }
