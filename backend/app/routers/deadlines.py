from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case as sa_case, delete, extract, func, select
from sqlalchemy.orm import Session, selectinload

from .. import deadlines as dl
from ..db import get_db
from ..filters import CaseFilter
from ..logic import log
from ..models import CalendarDay, Case, Deadline
from ..schemas import CalendarIn, DeadlinePatch, DeadlineOut, DeadlineWithCase
from ..security import Principal, require

router = APIRouter(prefix="/api/v1", tags=["Сроки"])


@router.get("/deadlines", response_model=list[DeadlineWithCase])
def list_deadlines(
    status: str = "open",
    due_before: date | None = None,
    due_after: date | None = None,
    assignee: str = "",
    kind: str = "",
    limit: int = Query(500, le=5000),
    f: CaseFilter = Depends(CaseFilter.dep),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer", scope="read")),
):
    stmt = select(Deadline).join(Case).options(selectinload(Deadline.case)).where(*f.where())
    if status:
        stmt = stmt.where(Deadline.status.in_(status.split(",")))
    if due_before:
        stmt = stmt.where(Deadline.due_date <= due_before)
    if due_after:
        stmt = stmt.where(Deadline.due_date >= due_after)
    if assignee:
        stmt = stmt.where(Deadline.assignee == assignee)
    if kind:
        stmt = stmt.where(Deadline.kind == kind)
    out = []
    for d in db.scalars(stmt.order_by(Deadline.due_date, Deadline.id).limit(limit)):
        o = DeadlineWithCase.model_validate(d)
        o.case_number, o.court_name, o.plaintiffs = d.case.case_number, d.case.court_name, d.case.plaintiffs
        out.append(o)
    return out


@router.patch("/deadlines/{deadline_id}", response_model=DeadlineOut)
def patch_deadline(deadline_id: int, body: DeadlinePatch, db: Session = Depends(get_db),
                   who: Principal = Depends(require(role="lawyer"))):
    d = db.get(Deadline, deadline_id)
    if d is None:
        raise HTTPException(404, "Срок не найден")
    if body.status and body.status not in ("open", "done", "cancelled"):
        raise HTTPException(400, "Статус: open | done | cancelled")
    changes = {}
    for k, v in body.model_dump(exclude_none=True).items():
        if getattr(d, k) != v:
            changes[k] = [str(getattr(d, k)), str(v)]
            setattr(d, k, v)
    if "due_date" in changes:
        d.auto = False  # дата поправлена юристом — автоматический пересчёт её больше не трогает
        d.rule += f"\nДата изменена вручную ({who.name})"
    if changes:
        log(db, who, "deadline_updated", "deadline", d.id, d.case_id, changes=changes)
    db.commit()
    return d


# --- Производственный календарь ----------------------------------------------------------------

@router.get("/calendar")
def calendar_status(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    y = extract("year", CalendarDay.day)
    rows = db.execute(select(y, func.count(), func.count(sa_case((CalendarDay.working.is_(False), 1))))
                      .group_by(y).order_by(y)).all()
    return [{"year": int(y), "days": n, "nonworking": int(nw or 0)} for y, n, nw in rows]


@router.put("/calendar")
def load_calendar(body: CalendarIn, db: Session = Depends(get_db),
                  who: Principal = Depends(require(role="admin", scope="calendar"))):
    """Загрузить год производственного календаря (из регламентированного календаря 1С).
    Перезаписывает год целиком и пересчитывает автоматические открытые сроки."""
    nonworking = set(body.nonworking)
    if any(d.year != body.year for d in nonworking):
        raise HTTPException(400, "Все даты должны относиться к указанному году")
    if not 100 <= len(nonworking) <= 140:
        raise HTTPException(400, f"Нерабочих дней {len(nonworking)} — похоже на неполные данные (ожидается 110–125)")
    db.execute(delete(CalendarDay).where(extract("year", CalendarDay.day) == body.year))
    d = date(body.year, 1, 1)
    while d.year == body.year:
        db.add(CalendarDay(day=d, working=d not in nonworking, source=body.source))
        d += timedelta(days=1)
    db.flush()
    cal = dl.WorkCalendar.from_db(db)
    case_ids = db.scalars(select(Deadline.case_id).where(Deadline.auto, Deadline.status == "open").distinct()).all()
    changed = 0
    for c in db.scalars(select(Case).where(Case.id.in_(case_ids)).options(selectinload(Case.documents), selectinload(Case.deadlines))):
        changed += len(dl.recalc_case(db, c, cal))
    log(db, who, "calendar_loaded", "calendar", None, year=body.year, nonworking=len(nonworking), deadlines_changed=changed)
    db.commit()
    return {"year": body.year, "nonworking": len(nonworking), "deadlines_changed": changed}
