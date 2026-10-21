"""Приём данных от сервисов системы автоматизации.

Все методы идемпотентны: повторная отправка тех же данных ничего не дублирует
(дело — по УИД / суду+номеру, наблюдение — по источнику+ключу, документ — по sha256).
Пакетные методы обрабатывают элементы независимо: ошибка одного не откатывает остальные.
"""
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import deadlines as dl
from ..db import get_db
from ..logic import add_observation, find_case, link_document, log, require_case, upsert_case
from ..models import Case, Document
from ..schemas import CaseIn, CaseUpsertResult, DocumentIn, DocumentResult, ObservationIn, ObservationResult
from ..security import Principal, require
from ..storage import StorageUnavailable, get_store, sha256_bytes

router = APIRouter(prefix="/api/v1/ingest", tags=["Приём данных (сервисы)"])

MAX_BATCH = 1000


def _batch(db: Session, items: list, fn):
    if len(items) > MAX_BATCH:
        raise HTTPException(413, f"Не больше {MAX_BATCH} элементов за запрос")
    results = []
    for i, item in enumerate(items):
        sp = db.begin_nested()
        try:
            results.append({"index": i, "ok": True, **fn(item)})
            sp.commit()
        except HTTPException as e:
            sp.rollback()
            results.append({"index": i, "ok": False, "error": e.detail})
        except Exception as e:  # noqa: BLE001 — ошибка отдельного элемента возвращается сервису
            sp.rollback()
            results.append({"index": i, "ok": False, "error": f"{type(e).__name__}: {e}"})
    db.commit()
    return results


@router.post("/cases")
def ingest_cases(items: list[CaseIn], db: Session = Depends(get_db), who: Principal = Depends(require(scope="ingest"))):
    """Создать/обновить дела. Ключ: УИД, иначе код суда + номер (основной или любой из aliases)."""
    def one(c: CaseIn):
        if not (c.uid or c.case_number):
            raise HTTPException(400, "Нужен УИД или номер дела")
        case, created, warnings = upsert_case(db, who, c)
        return CaseUpsertResult(case_id=case.id, created=created, warnings=warnings).model_dump()
    return _batch(db, items, one)


@router.post("/observations")
def ingest_observations(items: list[ObservationIn], db: Session = Depends(get_db),
                        who: Principal = Depends(require(scope="ingest"))):
    """Значения полей дела по источникам. Статус поля (подтверждено/конфликт) пересчитывается сразу."""
    def one(o: ObservationIn):
        case = require_case(db, o)
        obs = add_observation(db, who, case, o)
        return ObservationResult(observation_id=obs.id, case_id=case.id, field=o.field, status=obs.case_value.status).model_dump()
    return _batch(db, items, one)


def _upsert_document(db: Session, who: Principal, d: DocumentIn) -> tuple[Document, bool]:
    doc = db.scalar(select(Document).where(Document.sha256 == d.sha256.lower()))
    created = doc is None
    if created:
        doc = Document(sha256=d.sha256.lower())
        db.add(doc)
    fields = d.model_dump(exclude={"sha256", "case", "link_method", "meta"}, exclude_none=True)
    for k, v in fields.items():
        setattr(doc, k, v)
    if d.meta:
        doc.meta = {**(doc.meta or {}), **d.meta}
    db.flush()
    if d.case and d.case.model_dump(exclude_none=True):
        case = find_case(db, case_id=d.case.case_id, uid=d.case.uid, court_code=d.case.court_code, case_number=d.case.case_number)
        if case is None:
            doc.meta = {**doc.meta, "unresolved_case_ref": d.case.model_dump(exclude_none=True)}
        else:
            link_document(db, who, doc, case, d.link_method or ("УИД" if d.case.uid else "номер" if d.case.case_number else "id"))
    if doc.case_id and (created or {"act_type", "act_date", "motivated_date", "instance"} & fields.keys()):
        case = db.get(Case, doc.case_id)
        db.refresh(case)
        dl.recalc_case(db, case)
    log(db, who, "document_created" if created else "document_updated", "document", doc.id, doc.case_id,
        sha256=doc.sha256, act_type=doc.act_type)
    return doc, created


@router.post("/documents")
def ingest_documents(items: list[DocumentIn], db: Session = Depends(get_db), who: Principal = Depends(require(scope="ingest"))):
    """Метаданные документов (файл можно не передавать: storage_backend=external или docflow_id)."""
    def one(d: DocumentIn):
        doc, created = _upsert_document(db, who, d)
        return DocumentResult(document_id=doc.id, created=created, case_id=doc.case_id).model_dump()
    return _batch(db, items, one)


@router.post("/documents/upload", response_model=DocumentResult)
async def upload_document(
    file: UploadFile = File(...),
    meta: str = Form("{}", description="JSON по схеме DocumentIn; sha256 можно не указывать — посчитается"),
    signature: UploadFile | None = File(None, description="Открепленная подпись .sig"),
    db: Session = Depends(get_db),
    who: Principal = Depends(require(role="lawyer", scope="ingest")),
):
    """Загрузить файл документа (PDF/ZIP-оригинал письма и т.п.) в хранилище и создать/обновить карточку."""
    data = await file.read()
    sha = sha256_bytes(data)
    try:
        raw = json.loads(meta or "{}")
        if raw.get("sha256") and raw["sha256"].lower() != sha:
            raise HTTPException(400, "sha256 в meta не совпадает с файлом")
        d = DocumentIn.model_validate({**raw, "sha256": sha, "filename": raw.get("filename") or file.filename or "",
                                       "mime": raw.get("mime") or file.content_type or "application/pdf", "size": len(data)})
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(422, f"meta: {e}") from None
    try:
        store = get_store()
        ref = store.put(sha, data, d.filename, d.model_dump(mode="json", exclude={"text", "case"}))
        sig_ref = ""
        if signature is not None:
            sig = await signature.read()
            sig_ref = store.put(sha256_bytes(sig), sig, (d.filename or sha) + ".sig", {"signature_for": sha})
    except StorageUnavailable as e:
        raise HTTPException(503, str(e)) from None
    doc, created = _upsert_document(db, who, d)
    doc.storage_backend, doc.storage_ref = store.backend, ref
    if store.backend == "docflow":
        doc.docflow_id = ref
    if sig_ref:
        doc.signature_ref = sig_ref
    db.commit()
    return DocumentResult(document_id=doc.id, created=created, case_id=doc.case_id)
