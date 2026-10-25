"""Судебные заседания из внешнего календаря (например, «Судебный календарь» rasp.gslegalteam.ru).

Календарь — владелец записей: коннектор присылает полный снимок (snapshot) по источнику, рабочее место
добавляет новые, обновляет изменённые и помечает исчезнувшие removed. Привязка к делу — по номеру дела,
найденному в свободном тексте поля «дело»; не найдено или неоднозначно — юрист привязывает вручную,
и ручная привязка сохраняется при следующих снимках.
"""
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..logic import log
from ..models import Case, CaseAlias, Hearing
from ..notify import notify
from ..schemas import ORM
from ..security import Principal, require

router = APIRouter(prefix="/api/v1", tags=["Заседания"])

# 2-1234/2025, 33-123/2026, 88-4567/25, М-89/2026, 13-12/2026, 2а-…, А40-123/2026 (арбитраж)
CASE_NO = re.compile(r"(?<![\w-])((?:\d{1,2}[а-яА-Яa-z]{0,3}|[МмM]|[АA]\d{2})-\d{1,6}/\d{2,4})(?!\d)")


def case_numbers(text: str) -> list[str]:
    out = []
    for m in CASE_NO.findall(text or ""):
        n = m[0].upper() + m[1:] if m[0] in "мm" else m
        n = n.replace("M-", "М-")
        if n not in out:
            out.append(n)
    return out


def _variants(n: str) -> set[str]:
    """2-1234/2025 и 2-1234/25 — одно и то же дело: сравниваем обе записи года."""
    m = re.match(r"(.+/)(\d{2,4})$", n)
    if not m:
        return {n}
    head, y = m.groups()
    return {n, head + (y[-2:] if len(y) == 4 else "20" + y)}


def match_case(db: Session, numbers: list[str], court: str) -> int | None:
    """Дело по номерам из текста: единственное совпадение — привязка; несколько — уточнить по суду."""
    if not numbers:
        return None
    vs = set().union(*(_variants(n) for n in numbers))
    ids = set(db.scalars(select(Case.id).where(Case.case_number.in_(vs))))
    ids |= set(db.scalars(select(CaseAlias.case_id).where(CaseAlias.number.in_(vs))))
    if len(ids) == 1:
        return ids.pop()
    if len(ids) > 1 and court:
        word = court.split()[0].casefold()  # «Железнодорожный городской суд МО» → «железнодорожный»
        hits = [i for i in ids if word in (db.get(Case, i).court_name or "").casefold()]
        if len(hits) == 1:
            return hits[0]
    return None


class HearingIn(BaseModel):
    ext_uid: str = Field(min_length=1, max_length=128)
    date: date
    time: str = ""
    court: str = ""
    judge: str = ""
    case_text: str = ""
    plaintiff: str = ""
    defendant: str = ""
    owners: list[str] = []
    notes: str = ""
    highlight: str = ""


class HearingSnapshot(BaseModel):
    source: str = Field(min_length=1, max_length=64, description="Имя источника, напр. «Судебный календарь»")
    items: list[HearingIn]
    full: bool = Field(True, description="Полный снимок: записи источника, которых нет в items, помечаются removed")


class HearingOut(ORM):
    id: int
    source: str
    ext_uid: str
    date: date
    time: str
    court: str
    judge: str
    case_text: str
    case_numbers: list
    plaintiff: str
    defendant: str
    owners: list
    notes: str
    highlight: str
    case_id: int | None
    link_method: str
    removed: bool
    updated_at: datetime
    case_number: str | None = None


FIELDS = ("date", "time", "court", "judge", "case_text", "plaintiff", "defendant", "owners", "notes", "highlight")


@router.post("/ingest/hearings")
def ingest_hearings(body: HearingSnapshot, db: Session = Depends(get_db), who: Principal = Depends(require(scope="ingest"))):
    """Снимок заседаний из календаря. Идемпотентно: повтор того же снимка ничего не меняет."""
    existing = {h.ext_uid: h for h in db.scalars(select(Hearing).where(Hearing.source == body.source))}
    stats = {"created": 0, "updated": 0, "removed": 0, "restored": 0, "linked": 0, "unlinked": 0}
    seen = set()
    for it in body.items:
        seen.add(it.ext_uid)
        h = existing.get(it.ext_uid)
        data = it.model_dump(exclude={"ext_uid"})
        if h is None:
            h = Hearing(source=body.source, ext_uid=it.ext_uid, **data)
            db.add(h)
            stats["created"] += 1
        else:
            changed = {k for k in FIELDS if getattr(h, k) != data[k]}
            for k in changed:
                setattr(h, k, data[k])
            if h.removed:
                h.removed = False
                stats["restored"] += 1
            elif changed:
                stats["updated"] += 1
        h.case_numbers = case_numbers(f"{h.case_text} {h.notes}")
        if h.link_method != "вручную":  # ручную привязку юриста снимок не трогает
            cid = match_case(db, h.case_numbers, h.court)
            if cid != h.case_id:
                h.case_id, h.link_method = cid, ("номер" if cid else "")
        stats["linked" if h.case_id else "unlinked"] += 1
    if body.full:
        for uid, h in existing.items():
            if uid not in seen and not h.removed:
                h.removed = True
                stats["removed"] += 1
    db.flush()
    log(db, who, "hearings_synced", "hearing", None, source=body.source, **stats)
    db.commit()
    return stats


def _out(db: Session, h: Hearing) -> HearingOut:
    o = HearingOut.model_validate(h)
    if h.case_id:
        c = db.get(Case, h.case_id)
        o.case_number = c.case_number if c else None
    return o


@router.get("/hearings", response_model=list[HearingOut])
def list_hearings(date_from: date | None = None, date_to: date | None = None, case_id: int | None = None,
                  unlinked: bool | None = None, owner: str = "", q: str = "", include_removed: bool = False,
                  limit: int = Query(1000, ge=1, le=5000), db: Session = Depends(get_db),
                  _: Principal = Depends(require(role="viewer", scope="read"))):
    stmt = select(Hearing)
    if not include_removed:
        stmt = stmt.where(Hearing.removed.is_(False))
    if date_from:
        stmt = stmt.where(Hearing.date >= date_from)
    if date_to:
        stmt = stmt.where(Hearing.date <= date_to)
    if case_id:
        stmt = stmt.where(Hearing.case_id == case_id)
    if unlinked is not None:
        stmt = stmt.where(Hearing.case_id.is_(None) if unlinked else Hearing.case_id.is_not(None))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Hearing.case_text.ilike(like), Hearing.plaintiff.ilike(like), Hearing.court.ilike(like),
                              Hearing.judge.ilike(like), Hearing.notes.ilike(like)))
    rows = db.scalars(stmt.order_by(Hearing.date, Hearing.time, Hearing.id).limit(limit)).all()
    if owner:  # ответственные — список в JSON: фильтруем здесь (записей немного)
        rows = [h for h in rows if owner.casefold() in [o.casefold() for o in h.owners]]
    return [_out(db, h) for h in rows]


class LinkIn(BaseModel):
    case_id: int | None = None


@router.post("/hearings/{hearing_id}/link", response_model=HearingOut)
def link_hearing(hearing_id: int, body: LinkIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Ручная привязка заседания к делу (или отвязка: case_id = null). Сохраняется при следующих снимках."""
    h = db.get(Hearing, hearing_id)
    if h is None:
        raise HTTPException(404, "Заседание не найдено")
    if body.case_id and db.get(Case, body.case_id) is None:
        raise HTTPException(404, "Дело не найдено")
    old = h.case_id
    h.case_id, h.link_method = body.case_id, "вручную"
    log(db, who, "hearing_linked", "hearing", h.id, body.case_id or old, old_case_id=old, date=str(h.date))
    db.commit()
    return _out(db, h)


def remind_hearings(db: Session, today: date) -> int:
    """Напоминания о заседаниях ответственным по делу: за deadline_remind_days дней и в день заседания."""
    from datetime import timedelta

    days = get_settings().deadline_remind_days
    n = 0
    rows = db.scalars(select(Hearing).where(Hearing.removed.is_(False), Hearing.case_id.is_not(None),
                                            Hearing.date >= today, Hearing.date <= today + timedelta(days=days)))
    for h in rows:
        c = db.get(Case, h.case_id)
        if not c or not c.responsible:
            continue
        when = "сегодня" if h.date == today else h.date.strftime("%d.%m.%Y")
        n += notify(db, [c.responsible], "hearing", f"Заседание {when} {h.time}: дело № {c.case_number}".strip(),
                    body=f"{h.court}. {h.case_text}".strip(), link=f"/cases/{c.id}", case_id=c.id,
                    dedup=f"hearing:{h.id}:{h.date}:{'today' if h.date == today else 'soon'}")
    return n

