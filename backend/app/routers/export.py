"""Выдача данных наружу: лента изменений (для интеграции с 1С/Юрайт) и выгрузка решений файлом."""
import csv
import io
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..fields import field_def
from ..logic import log
from ..models import Case, CaseValue, Event
from ..schemas import ChangesOut, EventOut, Page
from ..security import Principal, require

router = APIRouter(prefix="/api/v1", tags=["Выгрузка и лента изменений"])

FEED_LOCK = 774_211  # ключ advisory-lock для присвоения номеров ленты


def sequence_feed(db: Session) -> None:
    """Присвоить номера ленты зафиксированным событиям без номера (по одному процессу за раз)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": FEED_LOCK})
    db.execute(text("""
        UPDATE events SET feed_seq = nextval('events_feed_seq')
        WHERE id IN (SELECT id FROM events WHERE feed_seq IS NULL ORDER BY id LIMIT 50000)
    """))
    db.commit()


@router.get("/changes", response_model=ChangesOut)
def changes(
    after: int = Query(0, ge=0, description="Курсор: next_cursor из прошлого ответа"),
    limit: int = Query(500, ge=1, le=5000),
    actions: str = Query("", description="Через запятую, напр. value_resolved,case_merged"),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer", scope="export")),
):
    """Лента изменений. Порядок — порядок фиксации; курсор монотонный, пропусков нет.
    Типичный цикл сервиса-интегратора: GET /changes?after=<сохранённый курсор> → применить → сохранить next_cursor."""
    sequence_feed(db)
    top = db.scalar(select(func.max(Event.feed_seq))) or 0  # граница чтения: всё до неё уже пронумеровано
    stmt = select(Event).where(Event.feed_seq > after, Event.feed_seq <= top)
    if actions:
        stmt = stmt.where(Event.action.in_(actions.split(",")))
    rows = db.scalars(stmt.order_by(Event.feed_seq).limit(limit)).all()
    # Если выдано меньше лимита — просмотрено всё до границы (с фильтром тоже), курсор = граница
    cursor = rows[-1].feed_seq if len(rows) == limit else max(after, top)
    return ChangesOut(items=rows, next_cursor=cursor)


@router.get("/journal", response_model=Page[EventOut])
def journal(
    actor: str = "",
    action: str = "",
    case_id: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer")),
):
    stmt = select(Event)
    if actor:
        stmt = stmt.where(Event.actor == actor)
    if action:
        stmt = stmt.where(Event.action.in_(action.split(",")))
    if case_id:
        stmt = stmt.where(Event.case_id == case_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Event.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page[EventOut](items=rows, total=total, page=page, size=size)


COLUMNS = ["УИД", "Код суда (1С)", "Суд", "Номер дела", "Другие номера", "Юрлицо", "Поле", "Поле (ключ)",
           "Значение", "Статус", "Кем решено", "Когда", "Комментарий"]
STATUS_RU = {"resolved": "решено юристом", "confirmed": "подтверждено источниками", "single": "один источник",
             "conflict": "конфликт", "appeal_possible": "возможна апелляция", "empty": "нет данных"}


def _rows(db: Session, statuses: list[str], since: date | None, fields: list[str]):
    stmt = (select(CaseValue).join(Case).where(CaseValue.status.in_(statuses))
            .options(selectinload(CaseValue.case).selectinload(Case.aliases)))
    if since:
        stmt = stmt.where(CaseValue.updated_at >= datetime.combine(since, datetime.min.time()))
    if fields:
        stmt = stmt.where(CaseValue.field.in_(fields))
    for v in db.scalars(stmt.order_by(Case.id, CaseValue.field)):
        c = v.case
        others = ", ".join(a.number for a in c.aliases if a.number != c.case_number)
        yield [c.uid or "", c.court_code, c.court_name, c.case_number, others, c.legal_entity,
               field_def(v.field).label, v.field, v.value or "", STATUS_RU.get(v.status, v.status),
               v.resolved_by or "", v.resolved_at.strftime("%d.%m.%Y %H:%M") if v.resolved_at else "", v.resolution_note]


@router.get("/export/values")
def export_values(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    status: str = Query("resolved", description="resolved — только решения юристов; добавьте confirmed для всех согласованных"),
    since: date | None = None,
    fields: str = "",
    db: Session = Depends(get_db),
    who: Principal = Depends(require(role="lawyer", scope="export")),
):
    """Файл для загрузки в 1С: итоговые значения полей по делам (ключ — УИД, запасной — код суда + номер)."""
    rows = list(_rows(db, status.split(","), since, [f for f in fields.split(",") if f]))
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    log(db, who, "export", "case_value", None, format=format, status=status, rows=len(rows))
    db.commit()
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(COLUMNS)
        w.writerows(rows)
        data, mime, name = ("﻿" + buf.getvalue()).encode(), "text/csv; charset=utf-8", f"решения_{stamp}.csv"
    else:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Значения"
        ws.append(COLUMNS)
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        for col, width in zip("ABCDEFGHIJKLM", [28, 12, 36, 16, 20, 18, 26, 16, 30, 22, 16, 16, 40]):
            ws.column_dimensions[col].width = width
        out = io.BytesIO()
        wb.save(out)
        data, mime, name = out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"решения_{stamp}.xlsx"
    return Response(data, media_type=mime, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
