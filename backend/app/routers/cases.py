from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case as sa_case, func, select
from sqlalchemy.orm import Session, selectinload

from .. import clock, deadlines as dl
from ..config import get_settings
from ..db import get_db
from ..fields import FIELDS, field_def
from ..filters import CaseFilter, facet_counts, flags, money
from .. import logic
from ..logic import log, merge_cases
from ..models import Case, CaseAlias, CaseValue, Deadline, Document, Event
from ..schemas import (CaseBrief, CaseCreate, CaseOut, CasePatch, DeadlineIn, DeadlineOut, DocumentBrief, EventOut, Page,
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
_money_fields = [k for k, f in FIELDS.items() if f.kind == "money" and k != "claim_total"]
# Присуждено — сумма согласованных/решённых денежных полей (кроме «заявлено»); спорные не учитываются
awarded_sq = (select(func.sum(money(CaseValue.value))).where(
    CaseValue.case_id == Case.id, CaseValue.field.in_(_money_fields), CaseValue.status.notin_(DISPUTED),
    CaseValue.value.is_not(None)).correlate(Case).scalar_subquery())
claimed_sq = (select(money(CaseValue.value)).where(
    CaseValue.case_id == Case.id, CaseValue.field == "claim_total", CaseValue.status.notin_(DISPUTED),
    CaseValue.value.is_not(None)).limit(1).correlate(Case).scalar_subquery())
next_title_sq = (select(Deadline.title).where(Deadline.case_id == Case.id, Deadline.status == "open")
                 .order_by(Deadline.due_date, Deadline.id).limit(1).correlate(Case).scalar_subquery())


def brief_rows(rows) -> list[CaseBrief]:
    out = []
    for c, n_conf, n_dl, nd, nt, aw, cl in rows:
        b = CaseBrief.model_validate(c)
        b.conflicts, b.open_deadlines, b.next_due, b.next_title = n_conf or 0, n_dl or 0, nd, nt
        b.awarded, b.claimed = (float(aw) if aw is not None else None), (float(cl) if cl is not None else None)
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
    f: CaseFilter = Depends(CaseFilter.dep),
    sort: str = Query("-updated_at", pattern="^-?(updated_at|case_number|conflicts|next_due|id)$"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=get_settings().page_size_max),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer", scope="read")),
):
    """Реестр дел. Все фильтры — см. CaseFilter (списочные параметры повторяются: ?building=401&building=308)."""
    stmt = select(Case, conflicts_sq.label("conflicts"), open_dl_sq.label("open_dl"), next_due_sq.label("next_due"),
                  next_title_sq.label("next_title"), awarded_sq.label("awarded"),
                  claimed_sq.label("claimed")).where(*f.where())
    total = db.scalar(select(func.count(Case.id)).where(*f.where()))  # без подзапросов колонок — быстрее
    key = sort.lstrip("-")
    col = {"updated_at": Case.updated_at, "case_number": Case.case_number, "id": Case.id,
           "conflicts": conflicts_sq, "next_due": next_due_sq}[key]
    order = col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last()
    rows = db.execute(stmt.order_by(order, Case.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page[CaseBrief](items=brief_rows(rows), total=total, page=page, size=size)


@router.get("/cases/facets")
def facets(f: CaseFilter = Depends(CaseFilter.dep), db: Session = Depends(get_db),
           _: Principal = Depends(require(role="viewer", scope="read"))):
    """Значения фильтров с числом дел (с учётом остальных выбранных фильтров) и числа для переключателей."""
    return {"facets": facet_counts(db, f), "flags": flags(db, f),
            "total": db.scalar(select(func.count(Case.id)).where(*f.where())),
            "sum_fields": [{"key": x.key, "label": x.label} for x in FIELDS.values() if x.kind == "money"]}


@router.get("/cases/duplicates")
def duplicates(uid: str = "", case_number: str = "", court_code: str = "", contract_no: str = "",
               building: str = "", flat: str = "", plaintiffs: str = "", exclude: int | None = None,
               db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    """Похожие дела — проверка перед заведением нового (по УИД, номеру, договору, квартире и истцам)."""
    q = CaseCreate(uid=uid or None, case_number=case_number or None, court_code=court_code or None,
                   contract_no=contract_no or None, building=building or None, flat=flat or None,
                   plaintiffs=plaintiffs or None)
    return logic.find_duplicates(db, q, exclude_id=exclude)


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
    """Правка реквизитов дела (любых). Изменения — в журнал и в ленту для внешних систем (case_updated)."""
    c = load_case(db, case_id)
    data = body.model_dump(exclude_unset=True)
    note = data.pop("note", "")
    logic.patch_case(db, who, c, data, note)
    db.commit()
    return CaseBrief.model_validate(c)


@router.post("/cases", response_model=CaseBrief, status_code=201)
def create_case(body: CaseCreate, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Завести дело вручную (например, по иску). Если найдены похожие дела и не указано force — 409 со списком."""
    if not (body.uid or body.case_number):
        raise HTTPException(400, "Нужен УИД или номер дела (для иска — номер материала М-…)")
    dups = logic.find_duplicates(db, body)
    if dups and not body.force:
        raise HTTPException(409, {"message": "Похожие дела уже есть — проверьте, не дубль ли это", "duplicates": dups})
    if body.uid and db.scalar(select(Case.id).where(Case.uid == body.uid.strip())):
        raise HTTPException(409, "Дело с таким УИД уже есть")
    if body.court_code and not body.court_name:
        body.court_name = logic.court_name_for(db, body.court_code)
    c = Case(uid=(body.uid or "").strip() or None, court_code=body.court_code or "", case_number=body.case_number or "")
    db.add(c)
    db.flush()
    data = body.model_dump(exclude={"force", "aliases", "extra", "uid", "court_code", "case_number"}, exclude_none=True)
    for k, v in data.items():
        setattr(c, k, v)
    for n in {x.strip() for x in [body.case_number or "", *body.aliases] if x and x.strip()}:
        c.aliases.append(CaseAlias(court_code=c.court_code, number=n))
    db.flush()
    log(db, who, "case_created", "case", c.id, c.id, uid=c.uid, number=c.case_number, manual=True,
        forced=bool(dups))
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
    """История дела, включая историю слитых в него дублей."""
    ids, frontier = {case_id}, [case_id]
    while frontier:  # слияния могут быть цепочкой: C ← B ← A
        merged = db.scalars(select(Event.data["merged_case_id"].as_integer()).where(
            Event.action == "case_merged", Event.case_id.in_(frontier))).all()
        frontier = [m for m in merged if m is not None and m not in ids]
        ids.update(frontier)
    return db.scalars(select(Event).where(Event.case_id.in_(ids)).order_by(Event.id.desc()).limit(get_settings().case_events_limit)).all()


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
    from datetime import timedelta

    today = clock.today()
    by_status = dict(db.execute(select(CaseValue.status, func.count()).group_by(CaseValue.status)).all())
    dl_counts = db.execute(select(
        func.count(sa_case((Deadline.due_date < today, 1))),
        func.count(sa_case(((Deadline.due_date >= today) & (Deadline.due_date <= today + timedelta(days=get_settings().soon_days)), 1))),
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
