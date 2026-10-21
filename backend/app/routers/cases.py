from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case as sa_case, func, select
from sqlalchemy.orm import Session, selectinload

from .. import deadlines as dl
from ..db import get_db
from ..fields import FIELDS, field_def
from ..logic import log, merge_cases, search_cases_filter
from ..models import Case, CaseValue, Deadline, Document, Event
from ..schemas import (CaseBrief, CaseOut, CasePatch, DeadlineIn, DeadlineOut, DocumentBrief, EventOut, Page,
                       ValueOut)
from ..security import Principal, require

router = APIRouter(prefix="/api/v1", tags=["Дела"])

DISPUTED = ("conflict", "appeal_possible")

conflicts_sq = (select(func.count()).where(CaseValue.case_id == Case.id, CaseValue.status.in_(DISPUTED))
                .correlate(Case).scalar_subquery())
open_dl_sq = (select(func.count()).where(Deadline.case_id == Case.id, Deadline.status == "open")
              .correlate(Case).scalar_subquery())
next_due_sq = (select(func.min(Deadline.due_date)).where(Deadline.case_id == Case.id, Deadline.status == "open")
               .correlate(Case).scalar_subquery())


def brief_rows(rows) -> list[CaseBrief]:
    out = []
    for c, n_conf, n_dl, nd in rows:
        b = CaseBrief.model_validate(c)
        b.conflicts, b.open_deadlines, b.next_due = n_conf or 0, n_dl or 0, nd
        out.append(b)
    return out


def value_out(v: CaseValue) -> ValueOut:
    o = ValueOut.model_validate(v)
    f = field_def(v.field)
    o.label, o.kind, o.group = f.label, f.kind, f.group
    o.observations.sort(key=lambda x: x.source)
    return o


@router.get("/fields")
def fields(_: Principal = Depends(require(role="viewer", scope="read"))):
    """Справочник сверяемых полей (ключ, подпись, тип, группа)."""
    return [f.__dict__ for f in FIELDS.values()]


@router.get("/cases", response_model=Page[CaseBrief])
def list_cases(
    q: str = "",
    court: str = "",
    legal_entity: str = "",
    building: str = "",
    stage: str = "",
    responsible: str = "",
    has_conflicts: bool | None = None,
    has_uid: bool | None = None,
    sort: str = Query("-updated_at", pattern="^-?(updated_at|case_number|conflicts|next_due|id)$"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer", scope="read")),
):
    stmt = select(Case, conflicts_sq.label("conflicts"), open_dl_sq.label("open_dl"), next_due_sq.label("next_due"))
    if q:
        stmt = stmt.where(search_cases_filter(q))
    if court:
        stmt = stmt.where(Case.court_name.ilike(f"%{court}%") | (Case.court_code == court))
    if legal_entity:
        stmt = stmt.where(Case.legal_entity == legal_entity)
    if building:
        stmt = stmt.where(Case.building == building)
    if stage:
        stmt = stmt.where(Case.stage == stage)
    if responsible:
        stmt = stmt.where(Case.responsible == responsible)
    if has_conflicts is not None:
        stmt = stmt.where((conflicts_sq > 0) if has_conflicts else (conflicts_sq == 0))
    if has_uid is not None:
        stmt = stmt.where(Case.uid.is_not(None) if has_uid else Case.uid.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    key = sort.lstrip("-")
    col = {"updated_at": Case.updated_at, "case_number": Case.case_number, "id": Case.id,
           "conflicts": conflicts_sq, "next_due": next_due_sq}[key]
    order = col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last()
    rows = db.execute(stmt.order_by(order, Case.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page[CaseBrief](items=brief_rows(rows), total=total, page=page, size=size)


@router.get("/cases/facets")
def facets(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    """Значения для фильтров реестра."""
    def distinct(col):
        return [r[0] for r in db.execute(select(col, func.count()).where(col != "").group_by(col).order_by(func.count().desc()).limit(300))]
    return {"legal_entity": distinct(Case.legal_entity), "stage": distinct(Case.stage),
            "responsible": distinct(Case.responsible), "building": distinct(Case.building)}


def load_case(db: Session, case_id: int) -> Case:
    c = db.scalar(select(Case).where(Case.id == case_id).options(
        selectinload(Case.aliases), selectinload(Case.values).selectinload(CaseValue.observations),
        selectinload(Case.documents), selectinload(Case.deadlines)))
    if c is None:
        raise HTTPException(404, "Дело не найдено")
    return c


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: int, db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    c = load_case(db, case_id)
    order = list(FIELDS)
    out = CaseOut.model_validate(c)
    out.values = sorted((value_out(v) for v in c.values),
                        key=lambda v: (order.index(v.field) if v.field in order else len(order), v.field))
    out.documents = sorted((DocumentBrief.model_validate(d) for d in c.documents),
                           key=lambda d: (d.act_date is None, d.act_date), reverse=False)
    out.deadlines = sorted((DeadlineOut.model_validate(d) for d in c.deadlines), key=lambda d: d.due_date)
    out.conflicts = sum(v.status in DISPUTED for v in c.values)
    open_dl = [d for d in c.deadlines if d.status == "open"]
    out.open_deadlines, out.next_due = len(open_dl), min((d.due_date for d in open_dl), default=None)
    return out


@router.patch("/cases/{case_id}", response_model=CaseBrief)
def patch_case(case_id: int, body: CasePatch, db: Session = Depends(get_db),
               who: Principal = Depends(require(role="lawyer"))):
    c = load_case(db, case_id)
    changes = {}
    for k, v in body.model_dump(exclude_none=True).items():
        if getattr(c, k) != v:
            changes[k] = [getattr(c, k), v]
            setattr(c, k, v)
    if changes:
        log(db, who, "case_updated", "case", c.id, c.id, changes=changes)
    db.commit()
    return CaseBrief.model_validate(c)


@router.post("/cases/{case_id}/merge/{other_id}", response_model=CaseBrief)
def merge(case_id: int, other_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Слить дело other_id в case_id (дубль под другим номером/УИД)."""
    target, source = load_case(db, case_id), load_case(db, other_id)
    merge_cases(db, who, target, source)
    db.commit()
    return CaseBrief.model_validate(target)


@router.get("/cases/{case_id}/events", response_model=list[EventOut])
def case_events(case_id: int, db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    return db.scalars(select(Event).where(Event.case_id == case_id).order_by(Event.id.desc()).limit(500)).all()


@router.post("/cases/{case_id}/deadlines", response_model=DeadlineOut)
def add_deadline(case_id: int, body: DeadlineIn, db: Session = Depends(get_db),
                 who: Principal = Depends(require(role="lawyer", scope="ingest"))):
    c = load_case(db, case_id)
    d = Deadline(case=c, kind=body.kind, title=body.title, due_date=body.due_date, start_date=body.start_date,
                 assignee=body.assignee, note=body.note, auto=False, rule="Введён вручную" if who.kind == "user" else f"Сервис {who.name}")
    db.add(d)
    db.flush()
    log(db, who, "deadline_added", "deadline", d.id, c.id, title=d.title, due=str(d.due_date))
    db.commit()
    return d


@router.post("/cases/{case_id}/deadlines/recalc", response_model=list[DeadlineOut])
def recalc(case_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    c = load_case(db, case_id)
    changed = dl.recalc_case(db, c)
    if changed:
        log(db, who, "deadlines_recalculated", "case", c.id, c.id, count=len(changed))
    db.commit()
    return sorted(c.deadlines, key=lambda d: d.due_date)


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    from datetime import date, timedelta

    today = date.today()
    by_status = dict(db.execute(select(CaseValue.status, func.count()).group_by(CaseValue.status)).all())
    dl_counts = db.execute(select(
        func.count(sa_case((Deadline.due_date < today, 1))),
        func.count(sa_case(((Deadline.due_date >= today) & (Deadline.due_date <= today + timedelta(days=7)), 1))),
    ).where(Deadline.status == "open")).one()
    return {
        "cases": db.scalar(select(func.count(Case.id))),
        "cases_with_uid": db.scalar(select(func.count(Case.id)).where(Case.uid.is_not(None))),
        "documents": db.scalar(select(func.count(Document.id))),
        "documents_unlinked": db.scalar(select(func.count(Document.id)).where(Document.case_id.is_(None))),
        "values_by_status": by_status,
        "deadlines_overdue": dl_counts[0],
        "deadlines_week": dl_counts[1],
    }
