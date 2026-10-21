from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Ссылки ------------------------------------------------------------------------------------

class CaseRef(BaseModel):
    """Как сервис указывает дело: id, или УИД, или код суда + номер (любой из псевдонимов)."""

    case_id: int | None = None
    uid: str | None = None
    court_code: str | None = None
    case_number: str | None = None


# --- Приём данных от сервисов -------------------------------------------------------------------

class CaseIn(BaseModel):
    uid: str | None = None
    court_code: str | None = None
    court_name: str | None = None
    case_number: str | None = None
    aliases: list[str] = []
    legal_entity: str | None = None
    complex: str | None = None
    building: str | None = None
    flat: str | None = None
    contract_no: str | None = None
    plaintiffs: str | None = None
    subject: str | None = None
    stage: str | None = None
    status: str | None = None
    outcome: str | None = None
    responsible: str | None = None
    appeal_flag: bool | None = None
    extra: dict[str, Any] = {}


class CaseUpsertResult(BaseModel):
    case_id: int
    created: bool
    warnings: list[str] = []


class ObservationIn(CaseRef):
    field: str = Field(description="Ключ поля, см. GET /api/v1/fields")
    source: str = Field(description="1С | отчёт | OCR | письмо | …")
    source_ref: str | None = Field(None, description="Ключ записи в источнике; один источник+ключ = одно наблюдение")
    value: str | float | int | None
    document_id: int | None = None
    document_sha256: str | None = None
    page: int | None = None
    quote: str | None = None
    confidence: float | None = None


class ObservationResult(BaseModel):
    observation_id: int
    case_id: int
    field: str
    status: str


class DocumentIn(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)
    filename: str = ""
    mime: str = "application/pdf"
    size: int | None = None
    pages: int | None = None
    kind: str | None = None
    act_type: str | None = None
    instance: str | None = None
    act_date: date | None = None
    motivated_date: date | None = None
    outcome: str | None = None
    track_no: str | None = None
    docflow_id: str | None = None
    storage_backend: str | None = Field(None, description="external — файл не загружается, лежит у источника")
    storage_ref: str | None = None
    text: str | None = None
    text_source: str | None = None
    meta: dict[str, Any] = {}
    case: CaseRef | None = None
    link_method: str | None = None


class DocumentResult(BaseModel):
    document_id: int
    created: bool
    case_id: int | None


class CalendarIn(BaseModel):
    year: int
    nonworking: list[date] = Field(description="Все нерабочие дни года (выходные + праздники с учётом переносов)")
    source: str = "1С"


# --- Ответы для интерфейса ---------------------------------------------------------------------

class AliasOut(ORM):
    court_code: str
    number: str


class ObservationOut(ORM):
    id: int
    source: str
    source_ref: str
    value: str
    value_num: float | None
    document_id: int | None
    page: int | None
    quote: str
    confidence: float | None
    observed_at: datetime


class ValueOut(ORM):
    id: int
    field: str
    label: str = ""
    kind: str = ""
    group: str = ""
    status: str
    value: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_note: str
    observations: list[ObservationOut] = []


class DocumentBrief(ORM):
    id: int
    sha256: str
    filename: str
    kind: str
    act_type: str
    instance: str
    act_date: date | None
    motivated_date: date | None
    outcome: str
    track_no: str
    storage_backend: str
    docflow_id: str
    link_method: str
    case_id: int | None
    pages: int | None


class DocumentOut(DocumentBrief):
    mime: str
    size: int | None
    text: str
    text_source: str
    signature_ref: str
    meta: dict
    created_at: datetime


class DeadlineOut(ORM):
    id: int
    case_id: int
    document_id: int | None
    kind: str
    title: str
    start_date: date | None
    due_date: date
    rule: str
    calendar_confirmed: bool
    auto: bool
    status: str
    assignee: str
    note: str


class DeadlineWithCase(DeadlineOut):
    case_number: str = ""
    court_name: str = ""
    plaintiffs: str = ""


class DeadlineIn(BaseModel):
    title: str
    kind: str = "custom"
    due_date: date
    start_date: date | None = None
    assignee: str = ""
    note: str = ""


class DeadlinePatch(BaseModel):
    due_date: date | None = None
    status: str | None = None
    assignee: str | None = None
    note: str | None = None


class CaseBrief(ORM):
    id: int
    uid: str | None
    court_code: str
    court_name: str
    case_number: str
    legal_entity: str
    complex: str
    building: str
    flat: str
    plaintiffs: str
    subject: str
    stage: str
    status: str
    outcome: str
    responsible: str
    appeal_flag: bool
    updated_at: datetime
    conflicts: int = 0
    open_deadlines: int = 0
    next_due: date | None = None


class CaseOut(CaseBrief):
    contract_no: str
    extra: dict
    aliases: list[AliasOut]
    values: list[ValueOut]
    documents: list[DocumentBrief]
    deadlines: list[DeadlineOut]


class CasePatch(BaseModel):
    responsible: str | None = None
    stage: str | None = None
    status: str | None = None


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int


class ResolveIn(BaseModel):
    observation_id: int | None = None
    value: str | None = None
    note: str = ""


class ReopenIn(BaseModel):
    note: str = ""


class ConflictOut(BaseModel):
    value: ValueOut
    case: CaseBrief


class EventOut(ORM):
    id: int
    ts: datetime
    actor_type: str
    actor: str
    action: str
    entity: str
    entity_id: int | None
    case_id: int | None
    data: dict
    feed_seq: int | None = None


class ChangesOut(BaseModel):
    items: list[EventOut]
    next_cursor: int


# --- Задачи ------------------------------------------------------------------------------------

class TaskIn(BaseModel):
    type: str
    payload: dict[str, Any] = {}
    priority: int = 100
    max_attempts: int = 3
    case_id: int | None = None
    document_id: int | None = None
    run_after: datetime | None = None


class TaskOut(ORM):
    id: int
    type: str
    status: str
    priority: int
    payload: dict
    result: dict | None
    error: str
    attempts: int
    max_attempts: int
    case_id: int | None
    document_id: int | None
    created_by: str
    locked_by: str
    lease_until: datetime | None
    created_at: datetime
    updated_at: datetime


class ClaimIn(BaseModel):
    types: list[str] = Field(default_factory=list, description="Пусто — типы, заданные сервису в настройках")
    limit: int = Field(1, ge=1, le=50)
    lease_seconds: int | None = Field(None, ge=30, le=86400)


class CompleteIn(BaseModel):
    result: dict[str, Any] = {}


class FailIn(BaseModel):
    error: str
    retry: bool = True
    retry_in_seconds: int = 60


class HeartbeatIn(BaseModel):
    lease_seconds: int | None = Field(None, ge=30, le=86400)


# --- Администрирование -------------------------------------------------------------------------

class ServiceIn(BaseModel):
    name: str
    description: str = ""
    scopes: list[str] = []
    task_types: list[str] = []


class ServicePatch(BaseModel):
    description: str | None = None
    scopes: list[str] | None = None
    task_types: list[str] | None = None
    active: bool | None = None


class ApiKeyOut(ORM):
    id: int
    prefix: str
    created_at: datetime
    revoked_at: datetime | None


class ServiceOut(ORM):
    id: int
    name: str
    description: str
    scopes: list[str]
    task_types: list[str]
    active: bool
    created_at: datetime
    last_seen: datetime | None
    keys: list[ApiKeyOut]


class NewKeyOut(BaseModel):
    service_id: int
    key: str = Field(description="Показывается один раз")


class UserOut(ORM):
    id: int
    login: str
    full_name: str
    email: str
    role: str
    active: bool
    last_login: datetime | None


class LoginIn(BaseModel):
    login: str
    password: str
