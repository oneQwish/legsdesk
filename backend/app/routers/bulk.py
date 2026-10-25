"""Массовые действия: по выбранным делам или по всем делам фильтра. Всегда сначала предпросмотр (dry_run),
каждое изменение — отдельной записью в журнале (как если бы юрист сделал его вручную)."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import logic
from ..db import get_db
from ..fields import field_def
from ..filters import CaseFilter
from ..models import Case, CaseValue
from ..security import Principal, require
from .cases import DISPUTED

router = APIRouter(prefix="/api/v1", tags=["Массовые действия"])

MAX_BULK = 2000


@router.get("/cases/ids")
def case_ids(f: CaseFilter = Depends(CaseFilter.dep), limit: int = Query(MAX_BULK, ge=1, le=MAX_BULK),
             db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    """id всех дел по фильтру — чтобы выбрать «все по фильтру» для массового действия."""
    return db.scalars(select(Case.id).where(*f.where()).order_by(Case.id).limit(limit)).all()


class BulkCases(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK)
    action: str = Field(pattern="^(responsible|stage|status|appeal_flag)$")
    value: str = ""
    note: str = ""
    dry_run: bool = True


@router.post("/cases/bulk")
def bulk_cases(body: BulkCases, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Поставить ответственного / стадию / статус / признак обжалования сразу многим делам."""
    value = body.value.strip().lower() if body.action == "responsible" else body.value.strip()
    if body.action == "appeal_flag":
        value = value.lower() in ("1", "true", "да")
    cases = db.scalars(select(Case).where(Case.id.in_(body.ids)).options(selectinload(Case.aliases))).all()
    changed = [c for c in cases if getattr(c, body.action) != value]
    preview = [{"id": c.id, "case_number": c.case_number, "plaintiffs": c.plaintiffs, "from": getattr(c, body.action), "to": value}
               for c in changed[:50]]
    if not body.dry_run:
        for c in changed:
            logic.patch_case(db, who, c, {body.action: value}, body.note or "массовое действие")
        db.commit()
    return {"selected": len(cases), "will_change": len(changed), "applied": not body.dry_run, "preview": preview}


class BulkResolve(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK)
    field: str
    source: str = Field(description="Принять значение этого источника (1С, отчёт, OCR, письмо…)")
    note: str = ""
    dry_run: bool = True


@router.post("/values/bulk-resolve")
def bulk_resolve(body: BulkResolve, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Разрешить спорные значения поля в выбранных делах значением одного источника. Дела, где этот
    источник не прислал значения, пропускаются (их надо разобрать вручную)."""
    vals = db.scalars(select(CaseValue).where(CaseValue.case_id.in_(body.ids), CaseValue.field == body.field,
                                              CaseValue.status.in_(DISPUTED))
                      .options(selectinload(CaseValue.observations), selectinload(CaseValue.case))).all()
    plan, skipped = [], []
    for v in vals:
        o = next((x for x in v.observations if x.source == body.source and x.normalized), None)
        (plan if o else skipped).append((v, o))
    preview = [{"case_id": v.case_id, "case_number": v.case.case_number, "value": o.value,
                "others": sorted({x.value for x in v.observations if x.source != body.source})} for v, o in plan[:50]]
    if not body.dry_run:
        note = body.note or f"массово: значение источника «{body.source}»"
        for v, o in plan:
            logic.resolve_value(db, who, v, None, o.id, note)
        db.commit()
    return {"disputed": len(vals), "will_resolve": len(plan), "skipped_no_source": len(skipped), "applied": not body.dry_run,
            "field_label": field_def(body.field).label, "preview": preview}


@router.get("/values/sources")
def sources(field: str, db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    """Какие источники присылали значения поля (для выбора в массовом разрешении)."""
    from ..models import Observation

    rows = db.execute(select(Observation.source).join(CaseValue).where(CaseValue.field == field).distinct()).all()
    return sorted(r[0] for r in rows)
