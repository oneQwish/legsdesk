"""Ежедневная работа: поручения, уведомления (колокольчик), обсуждение в деле с @упоминаниями."""
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..logic import log
from ..models import Assignment, Case, Comment, Notification, User
from ..notify import notify
from ..schemas import ORM
from ..security import Principal, require

router = APIRouter(prefix="/api/v1", tags=["Поручения, уведомления, обсуждение"])


# --- Поручения --------------------------------------------------------------------------------

class AssignmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    body: str = ""
    assignee: str = Field(min_length=1, max_length=128)
    due_date: date | None = None
    case_id: int | None = None
    case_ids: list[int] = Field(default=[], description="Одно поручение на каждое из дел (массовое действие)")


class AssignmentPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    assignee: str | None = None
    due_date: date | None = None
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    result: str | None = None


class AssignmentOut(ORM):
    id: int
    case_id: int | None
    title: str
    body: str
    assignee: str
    author: str
    due_date: date | None
    status: str
    result: str
    created_at: datetime
    done_at: datetime | None
    case_number: str | None = None
    plaintiffs: str | None = None


def _out(db: Session, a: Assignment) -> AssignmentOut:
    o = AssignmentOut.model_validate(a)
    if a.case_id:
        c = db.get(Case, a.case_id)
        if c:
            o.case_number, o.plaintiffs = c.case_number, c.plaintiffs
    return o


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(assignee: str = "", author: str = "", case_id: int | None = None, status: str = "open",
                     limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db),
                     _: Principal = Depends(require(role="viewer", scope="read"))):
    """Поручения. assignee=me — мои (для вошедшего пользователя)."""
    stmt = select(Assignment)
    if assignee:
        stmt = stmt.where(Assignment.assignee == assignee.lower())
    if author:
        stmt = stmt.where(Assignment.author == author.lower())
    if case_id:
        stmt = stmt.where(Assignment.case_id == case_id)
    if status:
        stmt = stmt.where(Assignment.status.in_(status.split(",")))
    rows = db.scalars(stmt.order_by(Assignment.due_date.asc().nulls_last(), Assignment.id).limit(limit)).all()
    return [_out(db, a) for a in rows]


@router.post("/assignments", response_model=list[AssignmentOut], status_code=201)
def create_assignment(body: AssignmentIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Дать поручение. С case_ids — по одному на каждое дело (массовое действие из реестра)."""
    ids = body.case_ids or [body.case_id]
    out = []
    for cid in ids:
        if cid is not None and db.get(Case, cid) is None:
            raise HTTPException(404, f"Дело #{cid} не найдено")
        a = Assignment(case_id=cid, title=body.title, body=body.body, assignee=body.assignee.strip().lower(),
                       author=who.name, due_date=body.due_date)
        db.add(a)
        db.flush()
        log(db, who, "assignment_created", "assignment", a.id, cid, title=a.title, assignee=a.assignee,
            due=str(a.due_date or ""))
        due = f" до {a.due_date.strftime('%d.%m.%Y')}" if a.due_date else ""
        notify(db, [a.assignee], "assignment", f"Поручение{due}: {a.title}", body=f"От {who.name}. {a.body}".strip(),
               link=f"/cases/{cid}" if cid else "/assignments", case_id=cid, skip=who.name)
        out.append(_out(db, a))
    db.commit()
    return out


@router.patch("/assignments/{assignment_id}", response_model=AssignmentOut)
def patch_assignment(assignment_id: int, body: AssignmentPatch, db: Session = Depends(get_db),
                     who: Principal = Depends(require(role="lawyer"))):
    a = db.get(Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "Поручение не найдено")
    changes = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "assignee" and v:
            v = v.strip().lower()
        if getattr(a, k) != v:
            changes[k] = [str(getattr(a, k)), str(v)]
            setattr(a, k, v)
    if "status" in changes:
        a.done_at = clock.now() if a.status == "done" else None
        if a.status == "done" and a.author != who.name:
            notify(db, [a.author], "assignment", f"Выполнено: {a.title}", body=a.result,
                   link=f"/cases/{a.case_id}" if a.case_id else "/assignments", case_id=a.case_id)
    if "assignee" in changes:
        notify(db, [a.assignee], "assignment", f"Вам передано поручение: {a.title}", body=a.body,
               link=f"/cases/{a.case_id}" if a.case_id else "/assignments", case_id=a.case_id, skip=who.name)
    if changes:
        log(db, who, "assignment_updated", "assignment", a.id, a.case_id, changes=changes)
    db.commit()
    return _out(db, a)


# --- Уведомления ------------------------------------------------------------------------------

class NotificationOut(ORM):
    id: int
    kind: str
    title: str
    body: str
    link: str
    case_id: int | None
    created_at: datetime
    read_at: datetime | None


@router.get("/notifications")
def my_notifications(unread: bool = False, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db),
                     who: Principal = Depends(require(role="viewer"))):
    stmt = select(Notification).where(Notification.login == who.name)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    items = db.scalars(stmt.order_by(Notification.id.desc()).limit(limit)).all()
    n_unread = db.scalar(select(func.count(Notification.id)).where(Notification.login == who.name,
                                                                   Notification.read_at.is_(None))) or 0
    return {"unread": n_unread, "items": [NotificationOut.model_validate(x) for x in items]}


@router.post("/notifications/read")
def mark_read(ids: list[int] = [], db: Session = Depends(get_db), who: Principal = Depends(require(role="viewer"))):
    """Отметить прочитанными: указанные или (пустой список) все."""
    stmt = update(Notification).where(Notification.login == who.name, Notification.read_at.is_(None))
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    n = db.execute(stmt.values(read_at=clock.now())).rowcount
    db.commit()
    return {"marked": n}


# --- Обсуждение в деле ------------------------------------------------------------------------

MENTION = re.compile(r"@([A-Za-z0-9._-]{2,64})")


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    pinned: bool = False


class CommentPatch(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=10000)
    pinned: bool | None = None


class CommentOut(ORM):
    id: int
    case_id: int
    author: str
    text: str
    mentions: list
    pinned: bool
    created_at: datetime
    edited_at: datetime | None


def _mentions(db: Session, text: str) -> list[str]:
    """@логины из текста — только существующие пользователи (иначе упоминание адресов почты и т. п.)."""
    found = {m.lower() for m in MENTION.findall(text)}
    if not found:
        return []
    known = set(db.scalars(select(User.login).where(User.login.in_(found))))
    return sorted(found & known)


@router.get("/cases/{case_id}/comments", response_model=list[CommentOut])
def comments(case_id: int, db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    return db.scalars(select(Comment).where(Comment.case_id == case_id)
                      .order_by(Comment.pinned.desc(), Comment.id.desc())).all()


@router.post("/cases/{case_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(case_id: int, body: CommentIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Дело не найдено")
    c = Comment(case_id=case_id, author=who.name, text=body.text.strip(), mentions=_mentions(db, body.text), pinned=body.pinned)
    db.add(c)
    db.flush()
    log(db, who, "comment_added", "comment", c.id, case_id, mentions=c.mentions, pinned=c.pinned)
    notify(db, c.mentions, "mention", f"{who.name} упомянул(а) вас в деле № {case.case_number or case.id}",
           body=c.text[:500], link=f"/cases/{case_id}?tab=discussion", case_id=case_id, skip=who.name)
    db.commit()
    return c


@router.patch("/comments/{comment_id}", response_model=CommentOut)
def patch_comment(comment_id: int, body: CommentPatch, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    c = db.get(Comment, comment_id)
    if c is None:
        raise HTTPException(404, "Комментарий не найден")
    if body.text is not None:
        if c.author != who.name:
            raise HTTPException(403, "Править текст может только автор")
        new = sorted(set(_mentions(db, body.text)) - set(c.mentions))
        c.text, c.mentions, c.edited_at = body.text.strip(), _mentions(db, body.text), clock.now()
        case = db.get(Case, c.case_id)
        notify(db, new, "mention", f"{who.name} упомянул(а) вас в деле № {case.case_number or case.id}",
               body=c.text[:500], link=f"/cases/{c.case_id}?tab=discussion", case_id=c.case_id, skip=who.name)
    if body.pinned is not None:
        c.pinned = body.pinned  # закрепить/открепить может любой юрист — это общая заметка по делу
    log(db, who, "comment_updated", "comment", c.id, c.case_id, pinned=c.pinned, edited=body.text is not None)
    db.commit()
    return c


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    c = db.get(Comment, comment_id)
    if c is None:
        raise HTTPException(404, "Комментарий не найден")
    if c.author != who.name and not who.has_role("admin"):
        raise HTTPException(403, "Удалить может автор или администратор")
    log(db, who, "comment_deleted", "comment", c.id, c.case_id, text=c.text[:500])
    db.delete(c)
    db.commit()


@router.get("/users/logins")
def logins(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer"))):
    """Логины и имена для подсказки @упоминаний и выбора исполнителя."""
    return [{"login": u.login, "name": u.full_name or u.login, "role": u.role}
            for u in db.scalars(select(User).where(User.active).order_by(User.login))]
