"""Исполнение: исполнительные листы и производства (Закон № 229-ФЗ) со сроками.

side = debtor — взыскивают с нашего юрлица (типично для дольщиков): срок добровольного исполнения —
5 рабочих дней со дня получения постановления о возбуждении (ч. 12 ст. 30 229-ФЗ); пропуск — исполнительский
сбор 7 % (ст. 112). side = creditor — взыскиваем мы: лист нужно предъявить в течение
[enforcement] writ_presentation_years лет со дня вступления решения в силу (ст. 21).
Сроки появляются в разделе «Сроки» и на «Столе» как обычные (виды voluntary и writ).
"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import deadlines as dl
from ..config import get_settings
from ..db import get_db
from ..logic import find_case, log
from ..models import Case, Deadline, Enforcement
from ..schemas import CaseRef, ORM
from ..security import Principal, require

router = APIRouter(prefix="/api/v1", tags=["Исполнение"])

STATUSES = ("лист получен", "лист предъявлен", "возбуждено", "окончено", "прекращено", "отозвано", "возвращено")
CLOSED = ("окончено", "прекращено", "отозвано", "возвращено")


class EnforcementIn(BaseModel):
    side: str = Field("debtor", pattern="^(debtor|creditor)$")
    writ_number: str = ""
    writ_date: date | None = None
    effective_date: date | None = None
    presentation_until: date | None = None
    ip_number: str = ""
    fssp_department: str = ""
    bailiff: str = ""
    start_date: date | None = None
    received_date: date | None = None
    status: str = "лист получен"
    amount: Decimal | None = None
    recovered: Decimal | None = None
    end_date: date | None = None
    notes: str = ""


class EnforcementCreate(EnforcementIn):
    case_id: int


class EnforcementPatch(BaseModel):
    side: str | None = Field(None, pattern="^(debtor|creditor)$")
    writ_number: str | None = None
    writ_date: date | None = None
    effective_date: date | None = None
    presentation_until: date | None = None
    ip_number: str | None = None
    fssp_department: str | None = None
    bailiff: str | None = None
    start_date: date | None = None
    received_date: date | None = None
    status: str | None = None
    amount: Decimal | None = None
    recovered: Decimal | None = None
    end_date: date | None = None
    notes: str | None = None


class EnforcementOut(EnforcementIn, ORM):
    id: int
    case_id: int
    created_at: datetime
    updated_at: datetime
    case_number: str | None = None
    plaintiffs: str | None = None


class EnforcementIngest(EnforcementIn, CaseRef):
    """Из ФССП/1С: ключ — номер ИП, иначе номер листа; дело — по CaseRef."""


def _check(e: Enforcement) -> None:
    if e.status not in STATUSES:
        raise HTTPException(400, f"Статус: {', '.join(STATUSES)}")


def sync_deadlines(db: Session, e: Enforcement) -> None:
    """Сроки по производству: создать/обновить/снять. Метка «[ИП №id]» в начале правила связывает срок с записью."""
    mark = f"[ИП №{e.id}]"
    case = db.get(Case, e.case_id)
    existing = {d.kind: d for d in case.deadlines if d.rule.startswith(mark)}
    want: dict[str, tuple[str, date, str]] = {}
    if e.status not in CLOSED:
        if e.side == "debtor" and e.received_date and e.status == "возбуждено":
            t = dl.working_days_term(dl.WorkCalendar.from_db(db), e.received_date, 5)
            want["voluntary"] = ("Добровольное исполнение (иначе сбор 7 %)", t.due,
                                 f"{mark} ч. 12 ст. 30 Закона № 229-ФЗ: 5 рабочих дней со дня получения постановления; {t.explain}")
        if e.side == "creditor" and e.presentation_until and e.status == "лист получен":
            want["writ"] = ("Предъявить исполнительный лист", e.presentation_until,
                            f"{mark} ст. 21 Закона № 229-ФЗ: {get_settings().writ_presentation_years} года со дня вступления в силу")
    for kind, (title, due, rule) in want.items():
        d = existing.get(kind)
        if d is None:
            db.add(Deadline(case_id=e.case_id, kind=kind, title=title, due_date=due, rule=rule, auto=True))
        elif d.auto:
            d.title, d.due_date, d.rule = title, due, rule
            if d.status == "cancelled":
                d.status = "open"
    for kind, d in existing.items():
        if kind not in want and d.status == "open":
            d.status = "cancelled"
            d.note = (d.note + "\n" if d.note else "") + "Снят: производство окончено или изменились данные."


def _apply(db: Session, e: Enforcement, data: dict) -> dict:
    changes = {}
    for k, v in data.items():
        if getattr(e, k) != v:
            changes[k] = [str(getattr(e, k)), str(v)]
            setattr(e, k, v)
    if e.effective_date and not data.get("presentation_until") and ("effective_date" in changes or e.presentation_until is None):
        e.presentation_until = dl.add_months(e.effective_date, 12 * get_settings().writ_presentation_years)
    _check(e)
    return changes


def _out(db: Session, e: Enforcement) -> EnforcementOut:
    o = EnforcementOut.model_validate(e)
    c = db.get(Case, e.case_id)
    o.case_number, o.plaintiffs = (c.case_number, c.plaintiffs) if c else (None, None)
    return o


@router.get("/enforcement", response_model=list[EnforcementOut])
def list_enforcement(case_id: int | None = None, status: str = "", side: str = "", active: bool | None = None,
                     limit: int = Query(1000, ge=1, le=5000), db: Session = Depends(get_db),
                     _: Principal = Depends(require(role="viewer", scope="read"))):
    stmt = select(Enforcement)
    if case_id:
        stmt = stmt.where(Enforcement.case_id == case_id)
    if status:
        stmt = stmt.where(Enforcement.status.in_(status.split(",")))
    if side:
        stmt = stmt.where(Enforcement.side == side)
    if active is not None:
        stmt = stmt.where(Enforcement.status.notin_(CLOSED) if active else Enforcement.status.in_(CLOSED))
    return [_out(db, e) for e in db.scalars(stmt.order_by(Enforcement.id.desc()).limit(limit))]


@router.get("/enforcement/summary")
def summary(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    rows = db.execute(select(Enforcement.side, Enforcement.status, func.count(), func.sum(Enforcement.amount),
                             func.sum(Enforcement.recovered)).group_by(Enforcement.side, Enforcement.status)).all()
    return [{"side": s, "status": st, "count": n, "amount": float(a or 0), "recovered": float(r or 0)} for s, st, n, a, r in rows]


@router.post("/enforcement", response_model=EnforcementOut, status_code=201)
def create(body: EnforcementCreate, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    if db.get(Case, body.case_id) is None:
        raise HTTPException(404, "Дело не найдено")
    e = Enforcement(case_id=body.case_id)
    db.add(e)
    _apply(db, e, body.model_dump(exclude={"case_id"}))
    db.flush()
    sync_deadlines(db, e)
    log(db, who, "enforcement_created", "enforcement", e.id, e.case_id, status=e.status, ip=e.ip_number, writ=e.writ_number)
    db.commit()
    return _out(db, e)


@router.patch("/enforcement/{eid}", response_model=EnforcementOut)
def patch(eid: int, body: EnforcementPatch, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    e = db.get(Enforcement, eid)
    if e is None:
        raise HTTPException(404, "Запись не найдена")
    changes = _apply(db, e, body.model_dump(exclude_unset=True))
    sync_deadlines(db, e)
    if changes:
        log(db, who, "enforcement_updated", "enforcement", e.id, e.case_id, changes=changes)
    db.commit()
    return _out(db, e)


@router.post("/ingest/enforcement")
def ingest(items: list[EnforcementIngest], db: Session = Depends(get_db), who: Principal = Depends(require(scope="ingest"))):
    """Загрузка из ФССП/1С. Ключ: номер ИП, иначе номер листа. Дело: case_id / УИД / суд+номер."""
    out = []
    for i, it in enumerate(items):
        case = find_case(db, case_id=it.case_id, uid=it.uid, court_code=it.court_code, case_number=it.case_number)
        if case is None:
            out.append({"index": i, "ok": False, "error": "дело не найдено"})
            continue
        key = (Enforcement.ip_number == it.ip_number) if it.ip_number else (Enforcement.writ_number == it.writ_number)
        if not (it.ip_number or it.writ_number):
            out.append({"index": i, "ok": False, "error": "нужен номер ИП или номер листа"})
            continue
        e = db.scalar(select(Enforcement).where(Enforcement.case_id == case.id, key))
        created = e is None
        if created:
            e = Enforcement(case_id=case.id)
            db.add(e)
        try:
            changes = _apply(db, e, it.model_dump(include=set(EnforcementIn.model_fields), exclude_unset=True))
        except HTTPException as ex:
            db.expunge(e) if created else None
            out.append({"index": i, "ok": False, "error": ex.detail})
            continue
        db.flush()
        sync_deadlines(db, e)
        if created or changes:
            log(db, who, "enforcement_created" if created else "enforcement_updated", "enforcement", e.id, e.case_id,
                status=e.status)
        out.append({"index": i, "ok": True, "id": e.id, "created": created})
    db.commit()
    return out
