"""Очередь задач поверх PostgreSQL.

Сервис забирает задачи (POST /tasks/claim) — строки блокируются через FOR UPDATE SKIP LOCKED, поэтому
несколько экземпляров одного сервиса не получат одну задачу дважды. Захват — аренда: если сервис упал
и не продлил её (heartbeat), задача после истечения аренды снова доступна (до max_attempts попыток).
"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..logic import log
from ..models import Service, Task
from ..schemas import ClaimIn, CompleteIn, FailIn, HeartbeatIn, Page, TaskIn, TaskOut
from ..security import Principal, require

router = APIRouter(prefix="/api/v1/tasks", tags=["Очередь задач"])


def now() -> datetime:
    return datetime.now(UTC)


@router.post("", response_model=TaskOut)
def create_task(body: TaskIn, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer", scope="tasks"))):
    t = Task(**body.model_dump(), created_by=who.name)
    db.add(t)
    db.flush()
    log(db, who, "task_created", "task", t.id, t.case_id, type=t.type)
    db.commit()
    return t


@router.get("", response_model=Page[TaskOut])
def list_tasks(status: str = "", type: str = "", page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500),
               db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="tasks"))):
    stmt = select(Task)
    if status:
        stmt = stmt.where(Task.status.in_(status.split(",")))
    if type:
        stmt = stmt.where(Task.type == type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Task.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page[TaskOut](items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary(db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="tasks"))):
    rows = db.execute(select(Task.type, Task.status, func.count()).group_by(Task.type, Task.status)).all()
    return [{"type": t, "status": s, "count": n} for t, s, n in rows]


@router.post("/claim", response_model=list[TaskOut])
def claim(body: ClaimIn, db: Session = Depends(get_db), who: Principal = Depends(require(scope="tasks"))):
    types = body.types or (db.get(Service, who.service_id).task_types or [])
    if not types:
        raise HTTPException(400, "Не указаны типы задач (в запросе или в настройках сервиса)")
    t_now = now()
    # Просроченная аренда при исчерпанных попытках — задача провалена
    db.execute(update(Task).where(Task.status == "running", Task.lease_until < t_now, Task.attempts >= Task.max_attempts)
               .values(status="failed", error="Аренда истекла, попытки исчерпаны", locked_by=""))
    claimable = or_(
        and_(Task.status == "queued", or_(Task.run_after.is_(None), Task.run_after <= t_now)),
        and_(Task.status == "running", Task.lease_until < t_now),
    )
    rows = db.scalars(select(Task).where(Task.type.in_(types), claimable)
                      .order_by(Task.priority, Task.id).limit(body.limit).with_for_update(skip_locked=True)).all()
    lease = timedelta(seconds=body.lease_seconds or get_settings().task_default_lease_seconds)
    for t in rows:
        t.status, t.locked_by, t.lease_until = "running", who.name, t_now + lease
        t.attempts += 1
    db.commit()
    return rows


def _own(db: Session, task_id: int, who: Principal) -> Task:
    t = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if t is None:
        raise HTTPException(404, "Задача не найдена")
    if t.status != "running" or t.locked_by != who.name:
        raise HTTPException(409, "Задача не захвачена этим сервисом (аренда могла истечь)")
    return t


@router.post("/{task_id}/heartbeat", response_model=TaskOut)
def heartbeat(task_id: int, body: HeartbeatIn, db: Session = Depends(get_db), who: Principal = Depends(require(scope="tasks"))):
    t = _own(db, task_id, who)
    t.lease_until = now() + timedelta(seconds=body.lease_seconds or get_settings().task_default_lease_seconds)
    db.commit()
    return t


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete(task_id: int, body: CompleteIn, db: Session = Depends(get_db), who: Principal = Depends(require(scope="tasks"))):
    t = _own(db, task_id, who)
    t.status, t.result, t.lease_until, t.error = "done", body.result, None, ""
    log(db, who, "task_done", "task", t.id, t.case_id, type=t.type)
    db.commit()
    return t


@router.post("/{task_id}/fail", response_model=TaskOut)
def fail(task_id: int, body: FailIn, db: Session = Depends(get_db), who: Principal = Depends(require(scope="tasks"))):
    t = _own(db, task_id, who)
    t.error, t.lease_until, t.locked_by = body.error[:10000], None, ""
    if body.retry and t.attempts < t.max_attempts:
        t.status, t.run_after = "queued", now() + timedelta(seconds=body.retry_in_seconds)
    else:
        t.status = "failed"
        log(db, who, "task_failed", "task", t.id, t.case_id, type=t.type, error=body.error[:500])
    db.commit()
    return t


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel(task_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "Задача не найдена")
    if t.status in ("done", "failed", "cancelled"):
        raise HTTPException(409, f"Задача уже в статусе {t.status}")
    t.status, t.locked_by, t.lease_until = "cancelled", "", None
    log(db, who, "task_cancelled", "task", t.id, t.case_id, type=t.type)
    db.commit()
    return t


@router.post("/{task_id}/retry", response_model=TaskOut)
def retry(task_id: int, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    t = db.get(Task, task_id)
    if t is None or t.status not in ("failed", "cancelled"):
        raise HTTPException(409, "Повторить можно только проваленную или отменённую задачу")
    t.status, t.attempts, t.run_after, t.error = "queued", 0, None, ""
    log(db, who, "task_retried", "task", t.id, t.case_id, type=t.type)
    db.commit()
    return t
