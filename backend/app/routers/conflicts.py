from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..filters import CaseFilter
from ..logic import reopen_value, resolve_value
from ..models import Case, CaseValue
from ..schemas import CaseBrief, ConflictOut, Page, ReopenIn, ResolveIn, ValueOut
from ..security import Principal, require
from .cases import value_out

router = APIRouter(prefix="/api/v1", tags=["Конфликты"])


@router.get("/conflicts", response_model=Page[ConflictOut])
def list_conflicts(
    field: str = "",
    f: CaseFilter = Depends(CaseFilter.dep),
    status: str = Query("conflict,appeal_possible"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer", scope="read")),
):
    """Очередь проверки: поля, где источники расходятся. Порядок — сначала дела с наибольшим числом конфликтов."""
    statuses = [s for s in status.split(",") if s]
    per_case = (select(CaseValue.case_id, func.count().label("n")).where(CaseValue.status.in_(statuses))
                .group_by(CaseValue.case_id).subquery())
    stmt = (select(CaseValue).join(Case).join(per_case, per_case.c.case_id == Case.id)
            .where(CaseValue.status.in_(statuses)))
    if field:
        stmt = stmt.where(CaseValue.field == field)
    stmt = stmt.where(*f.where())
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.options(selectinload(CaseValue.observations), selectinload(CaseValue.case))
                      .order_by(per_case.c.n.desc(), Case.id, CaseValue.field)
                      .offset((page - 1) * size).limit(size)).all()
    items = [ConflictOut(value=value_out(v), case=CaseBrief.model_validate(v.case)) for v in rows]
    return Page[ConflictOut](items=items, total=total, page=page, size=size)


@router.get("/conflicts/summary")
def summary(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    rows = db.execute(select(CaseValue.field, CaseValue.status, func.count())
                      .where(CaseValue.status.in_(("conflict", "appeal_possible")))
                      .group_by(CaseValue.field, CaseValue.status)).all()
    return [{"field": f, "status": s, "count": n} for f, s, n in rows]


def _load(db: Session, value_id: int) -> CaseValue:
    v = db.scalar(select(CaseValue).where(CaseValue.id == value_id)
                  .options(selectinload(CaseValue.observations), selectinload(CaseValue.case)))
    if v is None:
        raise HTTPException(404, "Поле не найдено")
    return v


@router.post("/values/{value_id}/resolve", response_model=ValueOut)
def resolve(value_id: int, body: ResolveIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Решение юриста: выбрать значение одного из источников (observation_id) или ввести своё (value + note)."""
    v = _load(db, value_id)
    resolve_value(db, who, v, body.value, body.observation_id, body.note)
    db.commit()
    return value_out(v)


@router.post("/values/{value_id}/reopen", response_model=ValueOut)
def reopen(value_id: int, body: ReopenIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    v = _load(db, value_id)
    if v.status != "resolved":
        raise HTTPException(400, "Поле не было разрешено")
    reopen_value(db, who, v, body.note)
    db.commit()
    return value_out(v)
