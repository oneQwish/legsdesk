from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..logic import link_document, log
from ..models import Case, Document, Observation
from ..schemas import CaseRef, DocumentBrief, DocumentOut, Page
from ..security import Principal, require
from ..storage import StorageUnavailable, get_store
from ..logic import require_case

router = APIRouter(prefix="/api/v1/documents", tags=["Документы"])

# Что браузер может показать прямо на странице. Остальное (в том числе HTML и SVG, присланные сервисом
# или пользователем) отдаётся только на скачивание: иначе файл со скриптом выполнился бы от имени юриста.
INLINE_MIME = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/tiff",
               "text/plain"}


@router.get("", response_model=Page[DocumentBrief])
def list_documents(
    q: str = "",
    kind: str = "",
    act_type: str = "",
    unlinked: bool | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Principal = Depends(require(role="viewer", scope="read")),
):
    stmt = select(Document)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Document.filename.ilike(like) | Document.track_no.ilike(like) | (Document.sha256 == q.lower()))
    if kind:
        stmt = stmt.where(Document.kind == kind)
    if act_type:
        stmt = stmt.where(Document.act_type.ilike(f"{act_type}%"))
    if unlinked is not None:
        stmt = stmt.where(Document.case_id.is_(None) if unlinked else Document.case_id.is_not(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Document.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page[DocumentBrief](items=rows, total=total, page=page, size=size)


def _doc(db: Session, doc_id: int) -> Document:
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "Документ не найден")
    return d


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    return _doc(db, doc_id)


@router.get("/{doc_id}/observations")
def document_observations(doc_id: int, db: Session = Depends(get_db),
                          _: Principal = Depends(require(role="viewer", scope="read"))):
    """Какие значения полей извлечены из этого документа (для просмотра рядом со сканом)."""
    rows = db.scalars(select(Observation).where(Observation.document_id == doc_id)).all()
    return [{"id": o.id, "field": o.case_value.field, "source": o.source, "value": o.value, "page": o.page,
             "quote": o.quote, "value_status": o.case_value.status, "case_value_id": o.case_value_id} for o in rows]


@router.get("/{doc_id}/file")
def get_file(doc_id: int, signature: bool = False, db: Session = Depends(get_db),
             who: Principal = Depends(require(role="viewer", scope="read"))):
    d = _doc(db, doc_id)
    ref = d.signature_ref if signature else d.storage_ref
    if not ref:
        raise HTTPException(404, "Файл не загружен в хранилище" + (" (подпись)" if signature else ""))
    try:
        data = get_store(d.storage_backend).open(ref)
    except StorageUnavailable as e:
        raise HTTPException(503, str(e)) from None
    name = d.filename or f"{d.sha256}.pdf"
    if signature:
        name, mime = name.rsplit(".", 1)[0] + ".sig", "application/pkcs7-signature"
    else:
        mime = d.mime
    mime = (mime or "application/octet-stream").split(";")[0].strip().lower()
    inline = mime in INLINE_MIME
    headers = {"Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(name)}",
               "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
    if mime != "application/pdf":  # встроенный просмотрщик PDF в Chrome не работает в песочнице
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    log(db, who, "document_viewed", "document", d.id, d.case_id, signature=signature)
    db.commit()
    if isinstance(data, bytes):
        return Response(data, media_type=mime, headers=headers)
    return StreamingResponse(data, media_type=mime, headers=headers)


@router.post("/{doc_id}/link", response_model=DocumentBrief)
def link(doc_id: int, ref: CaseRef, db: Session = Depends(get_db), who: Principal = Depends(require(role="lawyer"))):
    """Ручная привязка документа к делу (или отвязка: пустой CaseRef)."""
    d = _doc(db, doc_id)
    case: Case | None = None if not ref.model_dump(exclude_none=True) else require_case(db, ref)
    link_document(db, who, d, case, "вручную")
    db.commit()
    return d
