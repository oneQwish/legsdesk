"""Предметная логика: поиск и слияние дел, наблюдения по полям, статусы, решения юриста, журнал."""
from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import deadlines
from .config import get_settings
from .fields import field_def, normalize, parse_money
from .models import Case, CaseAlias, CaseValue, Document, Event, Observation
from .security import Principal


# Поля дела, которые дублируются в колонки карточки (для реестра и фильтров)
CASE_COLUMNS = {"plaintiffs", "complex", "building", "flat", "contract_no", "outcome", "subject"}


def log(db: Session, who: Principal | None, action: str, entity: str, entity_id: int | None,
        case_id: int | None = None, **data) -> Event:
    ev = Event(actor_type=who.kind if who else "system", actor=who.name if who else "system",
               action=action, entity=entity, entity_id=entity_id, case_id=case_id, data=data)
    db.add(ev)
    return ev


# --- Дела -------------------------------------------------------------------------------------

def find_case(db: Session, *, case_id: int | None = None, uid: str | None = None,
              court_code: str | None = None, case_number: str | None = None) -> Case | None:
    if case_id:
        return db.get(Case, case_id)
    if uid:
        c = db.scalar(select(Case).where(Case.uid == uid.strip()))
        if c:
            return c
    if case_number and court_code is not None:
        num = case_number.strip()
        c = db.scalar(select(Case).join(CaseAlias).where(CaseAlias.court_code == court_code, CaseAlias.number == num))
        if c:
            return c
        return db.scalar(select(Case).where(Case.court_code == court_code, Case.case_number == num))
    return None


def require_case(db: Session, ref) -> Case:
    c = find_case(db, case_id=ref.case_id, uid=ref.uid, court_code=ref.court_code, case_number=ref.case_number)
    if c is None:
        raise HTTPException(404, f"Дело не найдено: {ref.model_dump(exclude_none=True)}")
    return c


def upsert_case(db: Session, who: Principal, data) -> tuple[Case, bool, list[str]]:
    """Создать или обновить дело. Возвращает (дело, создано, предупреждения)."""
    warnings: list[str] = []
    numbers = [n.strip() for n in [data.case_number, *data.aliases] if n and n.strip()]
    case = find_case(db, uid=data.uid) if data.uid else None
    if case is None:
        for n in numbers:
            cand = find_case(db, court_code=data.court_code or "", case_number=n)
            # номер не уникален (один номер — разные УИД): дело с другим УИД — не то же самое дело
            if cand and not (data.uid and cand.uid and cand.uid != data.uid):
                case = cand
                break
    created = case is None
    if created:
        case = Case(uid=data.uid or None, court_code=data.court_code or "", case_number=data.case_number or (numbers[0] if numbers else ""))
        db.add(case)
        db.flush()
    elif data.uid and case.uid and case.uid != data.uid:
        other = case.extra.get("other_uids", [])
        if data.uid not in other:
            case.extra = {**case.extra, "other_uids": [*other, data.uid]}
        warnings.append(f"У дела {case.id} уже УИД {case.uid}; присланный {data.uid} сохранён как спорный")
    elif data.uid and not case.uid:
        case.uid = data.uid

    changes = {}
    for attr in ("court_name", "legal_entity", "complex", "building", "flat", "contract_no", "plaintiffs",
                 "subject", "stage", "status", "outcome", "responsible"):
        v = getattr(data, attr)
        if v is not None and getattr(case, attr) != v:
            changes[attr] = [getattr(case, attr), v]
            setattr(case, attr, v)
    if data.court_code and not case.court_code:
        case.court_code = data.court_code
    if data.case_number and not case.case_number:
        case.case_number = data.case_number
    if data.appeal_flag is not None:
        case.appeal_flag = data.appeal_flag
    if data.extra:
        case.extra = {**case.extra, **data.extra}

    have = {a.number for a in case.aliases}
    for n in numbers:
        if n in have:
            continue
        owner = db.scalar(select(CaseAlias).where(CaseAlias.court_code == case.court_code, CaseAlias.number == n))
        if owner and owner.case_id != case.id:
            warnings.append(f"Номер {n} уже принадлежит делу {owner.case_id} — не перенесён (возможный дубль, слить вручную)")
            continue
        case.aliases.append(CaseAlias(court_code=case.court_code, number=n))
        have.add(n)
    db.flush()
    if created:
        log(db, who, "case_created", "case", case.id, case.id, uid=case.uid, number=case.case_number)
    elif changes:
        log(db, who, "case_updated", "case", case.id, case.id, changes=changes)
    return case, created, warnings


def merge_cases(db: Session, who: Principal, target: Case, source: Case) -> None:
    """Слить дело source в target (одно дело под разными номерами/УИД)."""
    if target.id == source.id:
        raise HTTPException(400, "Нельзя слить дело само с собой")
    # Перенос через коллекции (а не case_id), иначе каскад delete-orphan у source удалит перенесённое
    for a in list(source.aliases):
        source.aliases.remove(a)
        if not any(x.number == a.number and x.court_code == a.court_code for x in target.aliases):
            target.aliases.append(a)
    db.flush()
    for v in list(source.values):
        tv = next((x for x in target.values if x.field == v.field), None)
        source.values.remove(v)
        if tv is None:
            target.values.append(v)
            continue
        for o in list(v.observations):
            v.observations.remove(o)
            if not any(x.source == o.source and x.source_ref == o.source_ref for x in tv.observations):
                tv.observations.append(o)
        db.flush()
        recompute(db, tv, target)
    for d in list(source.documents):
        d.case = target
    for d in list(source.deadlines):
        source.deadlines.remove(d)
        target.deadlines.append(d)
    if source.uid and source.uid != target.uid:
        other = target.extra.get("other_uids", [])
        target.extra = {**target.extra, "other_uids": other if source.uid in other else [*other, source.uid]}
    db.flush()
    log(db, who, "case_merged", "case", target.id, target.id, merged_case_id=source.id, merged_uid=source.uid,
        merged_number=source.case_number)
    db.delete(source)
    db.flush()


# --- Поля и наблюдения ------------------------------------------------------------------------

def _trust(source: str) -> int:
    """Чем левее источник в [values] source_trust, тем он надёжнее: его значение показывается при согласии."""
    order = get_settings().source_trust
    return order.index(source) if source in order else len(order)


def recompute(db: Session, cv: CaseValue, case: Case | None = None) -> str:
    """Пересчитать статус поля по наблюдениям. Возвращает новый статус."""
    case = case or cv.case
    obs = [o for o in cv.observations if o.normalized]
    distinct = {o.normalized for o in obs}
    old = cv.status
    if cv.status == "resolved":
        basis = set(cv.resolved_basis or [])
        fresh = distinct - basis - {normalize(cv.field, cv.value)}
        if not fresh:
            return cv.status
        cv.status = "conflict"
        cv.resolution_note = (cv.resolution_note + "\n" if cv.resolution_note else "") + \
            f"Открыто снова: новое значение источника ({', '.join(sorted(fresh))})"
        log(db, None, "value_reopened", "case_value", cv.id, case.id, field=cv.field, previous=cv.value, new_values=sorted(fresh))
        return cv.status
    if not distinct:
        cv.status, cv.value = "empty", None
    elif len(distinct) == 1:
        best = min(obs, key=lambda o: _trust(o.source))
        cv.value = best.value
        cv.status = "confirmed" if len({o.source for o in obs}) >= 2 else "single"
    else:
        cv.status = "appeal_possible" if case.appeal_flag and field_def(cv.field).kind == "money" else "conflict"
        cv.value = None
    if cv.field in CASE_COLUMNS and cv.value is not None:
        setattr(case, cv.field, cv.value)
    disputed = ("conflict", "appeal_possible")
    if old != cv.status and (old in disputed or cv.status in disputed):
        log(db, None, "value_status", "case_value", cv.id, case.id, field=cv.field, old=old, new=cv.status)
    if cv.status in disputed and old not in disputed and case.responsible:
        from .notify import notify

        notify(db, [case.responsible], "conflict", f"Источники расходятся: {field_def(cv.field).label} — дело № {case.case_number}",
               link=f"/cases/{case.id}", case_id=case.id, dedup=f"conflict:{cv.id}:{len(obs)}")
    return cv.status


def get_value(db: Session, case: Case, field: str) -> CaseValue:
    cv = next((v for v in case.values if v.field == field), None)
    if cv is None:
        cv = CaseValue(case=case, field=field)
        db.add(cv)
        db.flush()
    return cv


def add_observation(db: Session, who: Principal, case: Case, data) -> Observation:
    cv = get_value(db, case, data.field)
    ref = data.source_ref or ""
    o = next((x for x in cv.observations if x.source == data.source and x.source_ref == ref), None)
    value = "" if data.value is None else str(data.value)
    doc_id = None
    if data.document_sha256:
        doc = db.scalar(select(Document).where(Document.sha256 == data.document_sha256))
        doc_id = doc.id if doc else None
    elif data.document_id:
        doc_id = data.document_id
    kind = field_def(data.field).kind
    attrs = dict(value=value, normalized=normalize(data.field, value),
                 value_num=parse_money(value) if kind == "money" and value else None,
                 document_id=doc_id, page=data.page, quote=data.quote or "", confidence=data.confidence,
                 service_id=who.service_id)
    if o is None:
        o = Observation(case_value=cv, source=data.source, source_ref=ref, **attrs)
        db.add(o)
    else:
        for k, v in attrs.items():
            setattr(o, k, v)
    db.flush()
    db.refresh(cv)
    recompute(db, cv, case)
    return o


def resolve_value(db: Session, who: Principal, cv: CaseValue, value: str | None, observation_id: int | None, note: str) -> CaseValue:
    if observation_id:
        o = next((x for x in cv.observations if x.id == observation_id), None)
        if o is None:
            raise HTTPException(404, "Наблюдение не относится к этому полю")
        value, chosen = o.value, f"{o.source}" + (f" ({o.source_ref})" if o.source_ref else "")
    else:
        if value is None or not str(value).strip():
            raise HTTPException(400, "Укажите значение или выберите источник")
        if field_def(cv.field).kind == "money" and parse_money(value) is None:
            raise HTTPException(400, "Сумма не распознана: используйте формат 123456.78")
        chosen = "ручной ввод"
        if not note.strip():
            raise HTTPException(400, "Для своего значения нужен комментарий (откуда оно)")
    before = {"status": cv.status, "value": cv.value}
    cv.value = str(value)
    cv.status = "resolved"
    cv.resolved_by = who.name
    cv.resolved_at = datetime.now(UTC)
    cv.resolution_note = note
    cv.resolved_basis = sorted({o.normalized for o in cv.observations if o.normalized})
    if cv.field in CASE_COLUMNS:
        setattr(cv.case, cv.field, cv.value)
    log(db, who, "value_resolved", "case_value", cv.id, cv.case_id, field=cv.field, before=before,
        after={"value": cv.value}, chosen=chosen, note=note,
        sources={o.source + (f":{o.source_ref}" if o.source_ref else ""): o.value for o in cv.observations})
    return cv


def reopen_value(db: Session, who: Principal, cv: CaseValue, note: str) -> CaseValue:
    before = {"status": cv.status, "value": cv.value}
    cv.status, cv.resolved_by, cv.resolved_at, cv.resolved_basis = "single", None, None, None
    recompute(db, cv)
    log(db, who, "value_reopened", "case_value", cv.id, cv.case_id, field=cv.field, before=before, note=note)
    return cv


# --- Документы --------------------------------------------------------------------------------

def link_document(db: Session, who: Principal, doc: Document, case: Case | None, method: str) -> None:
    if doc.case_id == (case.id if case else None):
        return
    old = doc.case_id
    doc.case_id = case.id if case else None
    doc.link_method = method if case else ""
    db.flush()
    log(db, who, "document_linked", "document", doc.id, case.id if case else old, old_case_id=old, method=method)
    for cid in {old, doc.case_id} - {None}:
        c = db.get(Case, cid)
        if c is not None:
            db.refresh(c)
            deadlines.recalc_case(db, c)


def parse_iso(v: str | date | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v) if v else None


def search_cases_filter(q: str):
    like = f"%{q.strip()}%"
    return or_(Case.uid.ilike(like), Case.case_number.ilike(like), Case.plaintiffs.ilike(like),
               Case.contract_no.ilike(like), Case.court_name.ilike(like),
               Case.id.in_(select(CaseAlias.case_id).where(CaseAlias.number.ilike(like))))


# --- Правка и заведение дел юристом ----------------------------------------------------------

EDITABLE = ("uid", "court_code", "court_name", "case_number", "legal_entity", "complex", "building", "flat",
            "contract_no", "plaintiffs", "subject", "responsible", "stage", "status", "outcome", "appeal_flag")


def court_name_for(db: Session, code: str) -> str | None:
    from .models import Court

    c = db.get(Court, code) if code else None
    return c.name if c else None


def patch_case(db: Session, who: Principal, case: Case, data: dict, note: str = "") -> dict:
    """Изменить реквизиты дела. Возвращает {поле: [было, стало]}. Номер дела становится и псевдонимом."""
    changes: dict = {}
    if "uid" in data:
        uid = (data["uid"] or "").strip() or None
        if uid and uid != case.uid and db.scalar(select(Case.id).where(Case.uid == uid, Case.id != case.id)):
            raise HTTPException(409, f"УИД {uid} уже у другого дела — откройте его и слейте дубли")
        data["uid"] = uid
    if data.get("court_code") and not data.get("court_name") and data["court_code"] != case.court_code:
        name = court_name_for(db, data["court_code"])
        if name:
            data["court_name"] = name
    for k in EDITABLE:
        if k not in data:
            continue
        v = data[k] if k == "appeal_flag" or data[k] is None else str(data[k]).strip()
        if k != "uid" and v is None:
            continue
        if getattr(case, k) != v:
            changes[k] = [getattr(case, k), v]
            setattr(case, k, v)
    num = (data.get("case_number") or "").strip()
    if num and not any(a.number == num for a in case.aliases):
        owner = db.scalar(select(CaseAlias).where(CaseAlias.court_code == case.court_code, CaseAlias.number == num))
        if owner and owner.case_id != case.id:
            raise HTTPException(409, f"Номер {num} уже у дела #{owner.case_id} — это может быть дубль, слейте дела")
        case.aliases.append(CaseAlias(court_code=case.court_code, number=num))
    if changes:
        db.flush()
        log(db, who, "case_updated", "case", case.id, case.id, changes=changes, note=note)
        if "appeal_flag" in changes:
            for cv in case.values:
                if cv.status in ("conflict", "appeal_possible"):
                    cv.status = "single"  # пересчитать «возможна апелляция» по новому признаку
                    recompute(db, cv, case)
    return changes


def _norm_people(s: str) -> set[str]:
    """Фамилии из строки истцов: «Иванов И.И.; Петрова А.А.» → {"иванов", "петрова"}."""
    import re

    return {w for w in re.findall(r"[а-яёa-z]{3,}", (s or "").casefold().replace("ё", "е"))}


def find_duplicates(db: Session, data, exclude_id: int | None = None, limit: int = 10) -> list[dict]:
    """Похожие дела для нового: тот же УИД, тот же номер (у любого дела, в т.ч. псевдоним),
    тот же договор, или та же квартира с теми же истцами."""
    found: dict[int, list[str]] = {}

    def add(ids, why):
        for i in ids:
            if i != exclude_id:
                found.setdefault(i, []).append(why)

    if data.uid:
        add(db.scalars(select(Case.id).where(Case.uid == data.uid.strip())), "тот же УИД")
    nums = [n.strip() for n in [data.case_number, *(data.aliases or [])] if n and n.strip()]
    if nums:
        add(db.scalars(select(Case.id).where(Case.case_number.in_(nums))), "тот же номер дела")
        add(db.scalars(select(CaseAlias.case_id).where(CaseAlias.number.in_(nums))), "номер есть среди номеров дела")
    if data.contract_no and data.contract_no.strip():
        add(db.scalars(select(Case.id).where(Case.contract_no == data.contract_no.strip())), "тот же договор")
    if data.flat and data.building:
        people = _norm_people(data.plaintiffs or "")
        for c in db.scalars(select(Case).where(Case.building == data.building.strip(), Case.flat == data.flat.strip())):
            if not people or people & _norm_people(c.plaintiffs):
                add([c.id], "та же квартира" + (" и истцы" if people else ""))
    out = []
    for cid, why in list(found.items())[:limit]:
        c = db.get(Case, cid)
        out.append({"id": c.id, "uid": c.uid, "case_number": c.case_number, "court_name": c.court_name,
                    "plaintiffs": c.plaintiffs, "building": c.building, "flat": c.flat, "why": sorted(set(why))})
    return out
