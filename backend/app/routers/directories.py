"""Справочники: суды и юрлица. Читают все, правит администратор; сервисы загружают через /ingest/…"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..logic import log
from ..models import Case, Court, LegalEntity
from ..schemas import CourtIO, EntityIn, EntityOut
from ..security import Principal, require

router = APIRouter(prefix="/api/v1", tags=["Справочники"])


# --- Суды -------------------------------------------------------------------------------------

@router.get("/directories/courts", response_model=list[CourtIO])
def courts(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    return db.scalars(select(Court).order_by(Court.name)).all()


def _save_court(db: Session, who: Principal, body: CourtIO) -> Court:
    c = db.get(Court, body.code)
    created = c is None
    if created:
        c = Court(code=body.code)
        db.add(c)
    for k, v in body.model_dump(exclude={"code"}).items():
        setattr(c, k, v)
    db.flush()
    # дела этого суда без названия получают название из справочника
    for case in db.scalars(select(Case).where(Case.court_code == c.code, Case.court_name == "")):
        case.court_name = c.name
    log(db, who, "court_created" if created else "court_updated", "court", None, code=c.code, name=c.name)
    return c


@router.put("/directories/courts/{code}", response_model=CourtIO)
def put_court(code: str, body: CourtIO, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    if body.code != code:
        raise HTTPException(400, "Код в адресе и в теле не совпадают")
    c = _save_court(db, who, body)
    db.commit()
    return c


@router.delete("/directories/courts/{code}", status_code=204)
def delete_court(code: str, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    c = db.get(Court, code)
    if c is None:
        raise HTTPException(404, "Суд не найден")
    if db.scalar(select(Case.id).where(Case.court_code == code).limit(1)):
        raise HTTPException(409, "По этому суду есть дела — его можно только отключить (active = false)")
    db.delete(c)
    log(db, who, "court_deleted", "court", None, code=code)
    db.commit()


@router.post("/ingest/courts")
def ingest_courts(items: list[CourtIO], db: Session = Depends(get_db), who: Principal = Depends(require(scope="ingest"))):
    """Загрузка справочника судов из 1С или файла (по коду: есть — обновить, нет — добавить)."""
    for it in items:
        _save_court(db, who, it)
    db.commit()
    return {"count": len(items)}


# --- Юрлица -----------------------------------------------------------------------------------

@router.get("/directories/entities", response_model=list[EntityOut])
def entities(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    return db.scalars(select(LegalEntity).order_by(LegalEntity.name)).all()


def _save_entity(db: Session, who: Principal, body: EntityIn, entity_id: int | None = None) -> LegalEntity:
    e = db.get(LegalEntity, entity_id) if entity_id else db.scalar(select(LegalEntity).where(LegalEntity.name == body.name))
    created = e is None
    if created:
        e = LegalEntity()
        db.add(e)
    old_name = e.name
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, f"Юрлицо «{body.name}» уже есть в справочнике") from None
    if old_name and old_name != e.name:  # переименование — и в делах
        for case in db.scalars(select(Case).where(Case.legal_entity == old_name)):
            case.legal_entity = e.name
    log(db, who, "entity_created" if created else "entity_updated", "legal_entity", e.id, name=e.name)
    return e


@router.post("/directories/entities", response_model=EntityOut, status_code=201)
def add_entity(body: EntityIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    e = _save_entity(db, who, body)
    db.commit()
    return e


@router.put("/directories/entities/{entity_id}", response_model=EntityOut)
def put_entity(entity_id: int, body: EntityIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    if db.get(LegalEntity, entity_id) is None:
        raise HTTPException(404, "Юрлицо не найдено")
    e = _save_entity(db, who, body, entity_id)
    db.commit()
    return e


@router.post("/ingest/entities")
def ingest_entities(items: list[EntityIn], db: Session = Depends(get_db), who: Principal = Depends(require(scope="ingest"))):
    for it in items:
        _save_entity(db, who, it)
    db.commit()
    return {"count": len(items)}
