from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SavedView
from ..schemas import ORM
from ..security import Principal, require

router = APIRouter(prefix="/api/v1/views", tags=["Подборки"])

COLORS = ("ink", "seal", "ochre", "ok", "violet")


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    page: str = Field("cases", pattern="^(cases|conflicts|deadlines)$")
    params: str = Field("", max_length=4000)
    on_desk: bool = True
    color: str = "ink"


class ViewPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    params: str | None = Field(None, max_length=4000)
    on_desk: bool | None = None
    color: str | None = None
    position: int | None = None


class ViewOut(ORM):
    id: int
    name: str
    page: str
    params: str
    on_desk: bool
    color: str
    position: int


@router.get("", response_model=list[ViewOut])
def my_views(db: Session = Depends(get_db), who: Principal = Depends(require(role="viewer"))):
    return db.scalars(select(SavedView).where(SavedView.user_id == who.user_id)
                      .order_by(SavedView.position, SavedView.id)).all()


@router.post("", response_model=ViewOut)
def create_view(body: ViewIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="viewer"))):
    if body.color not in COLORS:
        raise HTTPException(400, f"Цвет: {', '.join(COLORS)}")
    pos = (db.scalar(select(func.max(SavedView.position)).where(SavedView.user_id == who.user_id)) or 0) + 1
    v = SavedView(user_id=who.user_id, position=pos, **body.model_dump())
    db.add(v)
    db.commit()
    return v


def _mine(db: Session, view_id: int, who: Principal) -> SavedView:
    v = db.get(SavedView, view_id)
    if v is None or v.user_id != who.user_id:
        raise HTTPException(404, "Подборка не найдена")
    return v


@router.patch("/{view_id}", response_model=ViewOut)
def patch_view(view_id: int, body: ViewPatch, db: Session = Depends(get_db), who: Principal = Depends(require(role="viewer"))):
    v = _mine(db, view_id, who)
    data = body.model_dump(exclude_none=True)
    if data.get("color") and data["color"] not in COLORS:
        raise HTTPException(400, f"Цвет: {', '.join(COLORS)}")
    for k, val in data.items():
        setattr(v, k, val)
    db.commit()
    return v


@router.delete("/{view_id}", status_code=204)
def delete_view(view_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="viewer"))):
    db.delete(_mine(db, view_id, who))
    db.commit()
