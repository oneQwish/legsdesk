"""Данные для «Стола»: лента дней со сроками, недельный прогресс пользователя, серия дней без просрочек."""
from datetime import UTC, date, datetime, timedelta

from fastapi import Depends, Query
from fastapi import APIRouter
from sqlalchemy import cast, func, select, Date
from sqlalchemy.orm import Session

from .. import clock, deadlines as dl
from ..config import get_settings
from ..db import get_db
from ..filters import CaseFilter
from ..models import Case, Deadline, Event, Hearing, User
from ..security import Principal, require

router = APIRouter(prefix="/api/v1/desk", tags=["Стол"])


@router.get("/strip")
def day_strip(
    days: int = Query(get_settings().desk_strip_days, ge=1, le=get_settings().desk_strip_max_days),
    f: CaseFilter = Depends(CaseFilter.dep),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer", scope="read")),
):
    """Лента дней от сегодня: открытые сроки по видам и признак рабочего дня (календарь 1С или запасной).
    Первая ячейка «просрочено» — все открытые сроки до сегодня."""
    today = clock.today()
    end = today + timedelta(days=days - 1)
    rows = db.execute(
        select(Deadline.due_date, Deadline.kind, func.count())
        .join(Case, Case.id == Deadline.case_id)
        .where(Deadline.status == "open", Deadline.due_date <= end, *f.where())
        .group_by(Deadline.due_date, Deadline.kind)
    ).all()
    # заседания из календаря: привязанные к делам — с учётом фильтров; без дела — только когда фильтров нет
    hq = (select(Hearing.date, func.count()).outerjoin(Case, Case.id == Hearing.case_id)
          .where(Hearing.removed.is_(False), Hearing.date >= today, Hearing.date <= end))
    conds = f.where()
    hq = hq.where(Hearing.case_id.is_not(None), *conds) if conds else hq
    rows = list(rows) + [(d, "hearing", n) for d, n in db.execute(hq.group_by(Hearing.date)).all()]
    cal = dl.WorkCalendar.from_db(db, {today.year, end.year})
    out, overdue = [], {}
    by_day: dict[date, dict[str, int]] = {}
    for d, kind, n in rows:
        if d < today:
            overdue[kind] = overdue.get(kind, 0) + n
        else:
            by_day.setdefault(d, {})[kind] = n
    for i in range(days):
        d = today + timedelta(days=i)
        kinds = by_day.get(d, {})
        out.append({"date": d.isoformat(), "working": cal.is_working(d), "total": sum(kinds.values()), "kinds": kinds})
    return {"overdue": {"total": sum(overdue.values()), "kinds": overdue}, "days": out,
            "calendar_confirmed": not cal.used_fallback}


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


@router.get("/progress")
def my_progress(db: Session = Depends(get_db), who: Principal = Depends(require(role="viewer"))):
    """Что пользователь сделал на этой неделе и на прошлой (по журналу) + серия дней без просрочек.

    Серия считается по делам, где пользователь ответственный; если таких нет — по всем делам.
    Срыв серии — день, когда открытый срок стал просроченным (сегодняшняя просрочка или срок,
    закрытый позже даты)."""
    now = datetime.now(UTC)
    # неделя — с понедельника по местному времени компании
    this_start = datetime.combine(_week_start(clock.today()), datetime.min.time(), clock.tz())
    last_start = this_start - timedelta(days=7)

    def count(action: str, start: datetime, end: datetime, data_filter=None) -> int:
        q = select(func.count(Event.id)).where(Event.actor == who.name, Event.action == action,
                                               Event.ts >= start, Event.ts < end)
        if data_filter is not None:
            q = q.where(data_filter)
        return db.scalar(q) or 0

    done_filter = Event.data["changes"]["status"][1].as_string() == "done"
    metrics = {}
    for key, action, flt in (("conflicts", "value_resolved", None), ("deadlines", "deadline_updated", done_filter),
                             ("documents", "document_linked", None)):
        metrics[key] = {"this_week": count(action, this_start, now + timedelta(seconds=1), flt),
                        "last_week": count(action, last_start, this_start, flt)}

    # серия дней без просрочек
    user = db.get(User, who.user_id)
    mine = select(Case.id).where(Case.responsible == who.name)
    scope_mine = db.scalar(select(func.count()).select_from(mine.subquery())) > 0
    case_scope = Deadline.case_id.in_(mine) if scope_mine else True
    today = clock.today()
    overdue_now = db.scalar(select(func.count(Deadline.id)).where(case_scope, Deadline.status == "open",
                                                                  Deadline.due_date < today)) or 0
    if overdue_now:
        streak = 0
    else:
        # последний срыв: срок закрыт позже своей даты (по событию закрытия)
        late = db.scalar(
            select(func.max(Deadline.due_date)).join(Event, (Event.entity == "deadline") & (Event.entity_id == Deadline.id))
            .where(case_scope, Event.action == "deadline_updated", done_filter, cast(Event.ts, Date) > Deadline.due_date))
        since = (late + timedelta(days=1)) if late else (
            db.scalar(select(func.min(cast(Event.ts, Date)))) or (user.last_login.date() if user and user.last_login else today))
        streak = max(0, (today - since).days)
    return {"metrics": metrics, "streak": streak, "overdue_now": overdue_now, "scope": "мои дела" if scope_mine else "все дела"}


@router.get("/piles")
def piles(size: int | None = Query(None, ge=1, le=200), db: Session = Depends(get_db),
          who: Principal = Depends(require(role="viewer"))):
    """Все стандартные стопки «Стола» одним запросом (раньше — шесть): горят сроки, на неделю, конфликты,
    мои дела, без УИД, недавно изменённые. Пороги — [interface] desk_hot_days / desk_week_days."""
    from .cases import list_cases

    s = get_settings()
    n = size or s.desk_pile_size
    today = clock.today()
    hot_to, week_to = today + timedelta(days=s.desk_hot_days), today + timedelta(days=s.desk_week_days)

    def pile(sort: str, **kw):
        page = list_cases(f=CaseFilter(**kw), sort=sort, page=1, size=n, db=db, _=who)
        return {"items": [i.model_dump(mode="json") for i in page.items], "total": page.total}

    week = pile("next_due", due_to=week_to)
    week_items = [i for i in week["items"] if i["next_due"] and i["next_due"] > hot_to.isoformat()]
    return {
        "hot": pile("next_due", due_to=hot_to),
        "week": {"items": week_items, "total": len(week_items)},
        "conflicts": pile("-conflicts", has_conflicts=True),
        "mine": pile("next_due", responsible=[who.name]),
        "no_uid": pile("-updated_at", has_uid=False),
        "recent": pile("-updated_at"),
    }
