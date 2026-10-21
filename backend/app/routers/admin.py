from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..logic import log
from ..models import ApiKey, Service, User
from ..schemas import NewKeyOut, ServiceIn, ServiceOut, ServicePatch, UserOut
from ..security import SCOPES, Principal, issue_api_key, require

router = APIRouter(prefix="/api/v1/admin", tags=["Администрирование"])


def _check_scopes(scopes: list[str]) -> None:
    bad = set(scopes) - SCOPES.keys()
    if bad:
        raise HTTPException(400, f"Неизвестные области: {', '.join(sorted(bad))}. Доступны: {', '.join(SCOPES)}")


@router.get("/scopes")
def scopes(_: Principal = Depends(require(role="admin"))):
    return SCOPES


@router.get("/services", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db), _: Principal = Depends(require(role="admin"))):
    return db.scalars(select(Service).options(selectinload(Service.keys)).order_by(Service.name)).all()


@router.post("/services", response_model=ServiceOut)
def create_service(body: ServiceIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    _check_scopes(body.scopes)
    s = Service(**body.model_dump())
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "Сервис с таким именем уже есть") from None
    log(db, who, "service_created", "service", s.id, name=s.name, scopes=s.scopes)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/services/{service_id}", response_model=ServiceOut)
def patch_service(service_id: int, body: ServicePatch, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    s = db.get(Service, service_id)
    if s is None:
        raise HTTPException(404, "Сервис не найден")
    data = body.model_dump(exclude_none=True)
    if "scopes" in data:
        _check_scopes(data["scopes"])
    for k, v in data.items():
        setattr(s, k, v)
    log(db, who, "service_updated", "service", s.id, **{k: v for k, v in data.items()})
    db.commit()
    db.refresh(s)
    return s


@router.post("/services/{service_id}/keys", response_model=NewKeyOut)
def new_key(service_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    s = db.get(Service, service_id)
    if s is None:
        raise HTTPException(404, "Сервис не найден")
    key = issue_api_key(db, s)
    log(db, who, "api_key_issued", "service", s.id, prefix=key.split("_")[1])
    db.commit()
    return NewKeyOut(service_id=s.id, key=key)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    k = db.get(ApiKey, key_id)
    if k is None:
        raise HTTPException(404, "Ключ не найден")
    if k.revoked_at is None:
        k.revoked_at = datetime.now(UTC)
        log(db, who, "api_key_revoked", "service", k.service_id, prefix=k.prefix)
        db.commit()


@router.get("/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), _: Principal = Depends(require(role="admin"))):
    return db.scalars(select(User).order_by(User.login)).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def set_active(user_id: int, active: bool, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    """Отключить пользователя в рабочем месте (роль управляется группами AD)."""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Пользователь не найден")
    u.active = active
    log(db, who, "user_active", "user", u.id, login=u.login, active=active)
    db.commit()
    return u
