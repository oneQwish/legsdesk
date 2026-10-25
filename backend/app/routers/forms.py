"""Печатные формы: шаблоны Word (.docx) с подстановкой данных дела.

Шаблон — обычный документ Word, в нужных местах которого написаны поля в двойных фигурных скобках:
{{ case.case_number }}, {{ case.plaintiffs }}, {{ v.amount_debt }}, {{ today }} … Список полей —
GET /api/v1/forms/variables (и в интерфейсе: «Печатные формы» → «Какие поля можно вставить»).
Шаблоны лежат в папке [documents] forms_dir (по умолчанию backend/forms); каждый .docx — одна форма,
название формы — имя файла. Администратор может загрузить новый шаблон из интерфейса.
"""
import io
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..fields import FIELDS, field_def
from ..logic import log
from ..models import Case, Court, Hearing, LegalEntity, User
from ..security import Principal, require
from .cases import load_case

router = APIRouter(prefix="/api/v1", tags=["Печатные формы"])

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def forms_dir() -> Path:
    d = get_settings().forms_dir
    return Path(d) if d else Path(__file__).resolve().parents[2] / "forms"


def _forms() -> list[dict]:
    d = forms_dir()
    return [{"key": p.stem, "title": p.stem.replace("_", " "), "file": p.name, "size": p.stat().st_size}
            for p in sorted(d.glob("*.docx")) if not p.name.startswith("~$")] if d.is_dir() else []


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    return str(v)


def money_words(v: str) -> str:
    """141611.96 → «141 611 руб. 96 коп.» (как пишут в процессуальных документах)."""
    m = re.fullmatch(r"\s*(-?\d+)(?:[.,](\d{1,2}))?\s*", str(v or ""))
    if not m:
        return str(v or "")
    rub = f"{int(m.group(1)):,}".replace(",", " ")
    return f"{rub} руб. {(m.group(2) or '0').ljust(2, '0')} коп."


def context(db: Session, case: Case, who: Principal) -> dict:
    """Всё, что можно вставить в шаблон. Ключи — латиницей, значения — готовый текст."""
    s = get_settings()
    user = db.scalar(select(User).where(User.login == who.name))
    court = db.get(Court, case.court_code) if case.court_code else None
    entity = db.scalar(select(LegalEntity).where(LegalEntity.name == case.legal_entity)) if case.legal_entity else None
    values = {v.field: v.value or "" for v in case.values if v.status not in ("conflict", "appeal_possible")}
    open_dl = sorted((d for d in case.deadlines if d.status == "open"), key=lambda d: d.due_date)
    hearing = db.scalar(select(Hearing).where(Hearing.case_id == case.id, Hearing.removed.is_(False),
                                              Hearing.date >= clock.today()).order_by(Hearing.date))
    return {
        "today": clock.today().strftime("%d.%m.%Y"),
        "user": {"login": who.name, "name": (user.full_name if user else "") or who.name, "email": user.email if user else ""},
        "case": {k: _fmt(getattr(case, k)) for k in ("id", "uid", "court_code", "court_name", "case_number", "legal_entity",
                                                    "complex", "building", "flat", "contract_no", "plaintiffs", "subject",
                                                    "stage", "status", "outcome", "responsible")}
                | {"numbers": ", ".join(a.number for a in case.aliases)},
        "court": {"name": court.name if court else case.court_name, "short_name": (court.short_name if court else "") or case.court_name,
                  "address": court.address if court else "", "region": court.region if court else ""},
        "entity": {"name": case.legal_entity, "full_name": (entity.full_name if entity else "") or case.legal_entity,
                   "inn": entity.inn if entity else "", "ogrn": entity.ogrn if entity else "", "address": entity.address if entity else ""},
        "v": {k: values.get(k, "") for k in FIELDS} | values,
        "money": {k: money_words(values[k]) for k in values if field_def(k).kind == "money"},
        "deadline": {"title": open_dl[0].title, "date": _fmt(open_dl[0].due_date)} if open_dl else {"title": "", "date": ""},
        "hearing": {"date": _fmt(hearing.date), "time": hearing.time, "court": hearing.court} if hearing else {"date": "", "time": "", "court": ""},
        "public_url": s.public_url,
    }


@router.get("/forms")
def list_forms(_: Principal = Depends(require(role="viewer"))):
    return _forms()


@router.get("/forms/variables")
def variables(_: Principal = Depends(require(role="viewer"))):
    """Что можно вставить в шаблон: {{ поле }} → пояснение."""
    out = {"{{ today }}": "сегодняшняя дата", "{{ user.name }}": "кто формирует документ (ФИО из AD)",
           "{{ case.case_number }}": "номер дела", "{{ case.uid }}": "УИД", "{{ case.numbers }}": "все номера дела",
           "{{ case.plaintiffs }}": "истцы", "{{ case.complex }}, {{ case.building }}, {{ case.flat }}": "ЖК, корпус, квартира",
           "{{ case.contract_no }}": "договор", "{{ case.subject }}": "предмет иска", "{{ case.responsible }}": "ответственный",
           "{{ court.name }}, {{ court.address }}": "суд (из справочника)",
           "{{ entity.full_name }}, {{ entity.inn }}, {{ entity.ogrn }}, {{ entity.address }}": "юрлицо (из справочника)",
           "{{ deadline.title }}, {{ deadline.date }}": "ближайший открытый срок",
           "{{ hearing.date }}, {{ hearing.time }}": "ближайшее заседание"}
    for k, f in FIELDS.items():
        out[f"{{{{ v.{k} }}}}"] = f.label
        if f.kind == "money":
            out[f"{{{{ money.{k} }}}}"] = f"{f.label} — «141 611 руб. 96 коп.»"
    return out


@router.post("/cases/{case_id}/forms/{key}")
def make_form(case_id: int, key: str, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Заполнить шаблон данными дела и отдать .docx (документ открывается в Word для доработки)."""
    from docxtpl import DocxTemplate
    from jinja2 import TemplateError

    path = next((forms_dir() / f["file"] for f in _forms() if f["key"] == key), None)
    if path is None:
        raise HTTPException(404, "Шаблон не найден")
    case = load_case(db, case_id)
    doc = DocxTemplate(path)
    try:
        doc.render(context(db, case, who), autoescape=True)
    except TemplateError as e:
        raise HTTPException(422, f"Ошибка в шаблоне «{path.name}»: {e} — проверьте {{{{ … }}}} в документе") from None
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    log(db, who, "form_generated", "case", case.id, case.id, form=path.name)
    db.commit()
    name = f"{path.stem} — {case.case_number or case.id}.docx".replace("/", "-")
    return StreamingResponse(buf, media_type=DOCX, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.post("/forms", status_code=201)
async def upload_form(file: UploadFile = File(...), db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    """Добавить или заменить шаблон (.docx). Название формы — имя файла."""
    name = Path(file.filename or "").name
    if not name.lower().endswith(".docx") or name.startswith("."):
        raise HTTPException(400, "Нужен файл Word .docx")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024 or not data.startswith(b"PK"):
        raise HTTPException(400, "Файл не похож на документ Word .docx (или больше 20 МБ)")
    from docxtpl import DocxTemplate
    from jinja2 import TemplateError

    try:  # проверить, что шаблон вообще собирается, — до сохранения
        DocxTemplate(io.BytesIO(data)).get_undeclared_template_variables()
    except (TemplateError, Exception) as e:  # noqa: BLE001
        raise HTTPException(422, f"Шаблон не читается: {e}") from None
    d = forms_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    log(db, who, "form_uploaded", "form", None, file=name)
    db.commit()
    return {"key": Path(name).stem, "file": name}


@router.delete("/forms/{key}", status_code=204)
def delete_form(key: str, db: Session = Depends(get_db), who: Principal = Depends(require(role="admin"))):
    f = next((f for f in _forms() if f["key"] == key), None)
    if f is None:
        raise HTTPException(404, "Шаблон не найден")
    (forms_dir() / f["file"]).unlink()
    log(db, who, "form_deleted", "form", None, file=f["file"])
    db.commit()

