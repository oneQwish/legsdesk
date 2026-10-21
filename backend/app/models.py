"""Модель данных рабочего места.

Дело — единица учёта (иск → решение → апелляция/кассация). Идентичность дела — УИД; номера дел
(М-, 2-, 33-, 88-) — псевдонимы в case_aliases. Каждое сверяемое поле дела (case_values) собирает
наблюдения из источников (value_observations: 1С, отчёт, OCR, цифровое письмо…), статус поля
вычисляется по их согласию; юрист разрешает конфликт, решение пишется в журнал (events), который
одновременно служит лентой изменений для 1С.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

FEED_SEQ = Sequence("events_feed_seq", metadata=Base.metadata)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(128), unique=True)
    full_name: Mapped[str] = mapped_column(String(256), default="")
    email: Mapped[str] = mapped_column(String(256), default="")
    role: Mapped[str] = mapped_column(String(32), default="viewer")  # admin | lawyer | viewer
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Service(Base):
    """Внешний сервис системы автоматизации, подключённый к API."""

    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    task_types: Mapped[list] = mapped_column(JSON, default=list)  # какие задачи сервис умеет брать
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    keys: Mapped[list["ApiKey"]] = relationship(back_populates="service")


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service: Mapped[Service] = relationship(back_populates="keys")


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str | None] = mapped_column(String(64), unique=True)  # УИД, напр. 50RS0010-01-2025-000287-27
    court_code: Mapped[str] = mapped_column(String(64), default="")  # код суда в справочнике 1С
    court_name: Mapped[str] = mapped_column(String(512), default="")
    case_number: Mapped[str] = mapped_column(String(64), default="")  # основной номер (2-…)
    legal_entity: Mapped[str] = mapped_column(String(128), default="")
    complex: Mapped[str] = mapped_column(String(128), default="")
    building: Mapped[str] = mapped_column(String(32), default="")
    flat: Mapped[str] = mapped_column(String(32), default="")
    contract_no: Mapped[str] = mapped_column(String(64), default="")
    plaintiffs: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(String(256), default="")
    stage: Mapped[str] = mapped_column(String(64), default="")  # иск | 1-я инстанция | апелляция | кассация | исполнение
    status: Mapped[str] = mapped_column(String(128), default="")
    outcome: Mapped[str] = mapped_column(String(128), default="")
    appeal_flag: Mapped[bool] = mapped_column(Boolean, default=False)  # есть признаки обжалования
    responsible: Mapped[str] = mapped_column(String(128), default="")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    aliases: Mapped[list["CaseAlias"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    values: Mapped[list["CaseValue"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="case")
    deadlines: Mapped[list["Deadline"]] = relationship(back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_cases_court_number", "court_code", "case_number"),)


class CaseAlias(Base):
    """Все номера дела: М-материал, 2-… (в т.ч. прежние), 33-… апелляции, 88-… кассации."""

    __tablename__ = "case_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    court_code: Mapped[str] = mapped_column(String(64), default="")
    number: Mapped[str] = mapped_column(String(64))
    case: Mapped[Case] = relationship(back_populates="aliases")
    __table_args__ = (UniqueConstraint("court_code", "number", name="uq_alias_court_number"),)


class CaseValue(Base):
    """Сверяемое поле дела. status: confirmed | single | conflict | appeal_possible | resolved | empty."""

    __tablename__ = "case_values"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="empty", index=True)
    value: Mapped[str | None] = mapped_column(Text)  # текущее итоговое значение (согласованное или решение юриста)
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    # приведённые значения источников на момент решения: новое, ранее не виденное значение снова открывает конфликт
    resolved_basis: Mapped[list | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    case: Mapped[Case] = relationship(back_populates="values")
    observations: Mapped[list["Observation"]] = relationship(back_populates="case_value", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("case_id", "field", name="uq_case_field"),)


class Observation(Base):
    """Значение поля по одному источнику (с цитатой и ссылкой на документ, если есть)."""

    __tablename__ = "value_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_value_id: Mapped[int] = mapped_column(ForeignKey("case_values.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(64))  # 1С | отчёт | OCR | письмо | ручной | …
    source_ref: Mapped[str] = mapped_column(String(256), default="")  # ключ записи в источнике (строка выгрузки, id документа…)
    value: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    page: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column()
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    case_value: Mapped[CaseValue] = relationship(back_populates="observations")
    document: Mapped["Document | None"] = relationship()
    __table_args__ = (UniqueConstraint("case_value_id", "source", "source_ref", name="uq_obs_source"),)


class Document(Base):
    """Документ (скан, цифровой оригинал письма, иск, акт ФССП…). Файл — во внешнем хранилище."""

    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(512), default="")
    mime: Mapped[str] = mapped_column(String(128), default="application/pdf")
    size: Mapped[int | None] = mapped_column(BigInteger)
    pages: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(64), default="скан")  # скан | письмо | иск | возражение | ФССП | прочее
    act_type: Mapped[str] = mapped_column(String(128), default="")  # решение | определение о судебных расходах | апелляционное определение …
    instance: Mapped[str] = mapped_column(String(32), default="")  # первая | апелляция | кассация
    act_date: Mapped[date | None] = mapped_column(Date)
    motivated_date: Mapped[date | None] = mapped_column(Date)  # решение в окончательной форме
    outcome: Mapped[str] = mapped_column(String(256), default="")
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), index=True)
    link_method: Mapped[str] = mapped_column(String(64), default="")  # УИД | номер | текст | вручную
    track_no: Mapped[str] = mapped_column(String(32), default="")  # трек Почты России (электронное письмо)
    storage_backend: Mapped[str] = mapped_column(String(32), default="")  # local | docflow | external
    storage_ref: Mapped[str] = mapped_column(String(512), default="")
    signature_ref: Mapped[str] = mapped_column(String(512), default="")  # .sig рядом с оригиналом
    docflow_id: Mapped[str] = mapped_column(String(128), default="")  # карточка в 1С:ДО
    text: Mapped[str] = mapped_column(Text, default="")
    text_source: Mapped[str] = mapped_column(String(32), default="")  # OCR | цифровой | очищенный
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    case: Mapped[Case | None] = relationship(back_populates="documents")


class Deadline(Base):
    """Процессуальный срок. auto=True — посчитан правилом из акта; правка юриста делает его ручным."""

    __tablename__ = "deadlines"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(64))  # appeal | cassation | private_complaint | effective | hearing | custom
    title: Mapped[str] = mapped_column(String(256))
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    rule: Mapped[str] = mapped_column(Text, default="")  # как посчитано (статья, от какой даты, переносы)
    calendar_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)  # календарь года загружен из 1С
    auto: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open | done | cancelled
    assignee: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    case: Mapped[Case] = relationship(back_populates="deadlines")
    document: Mapped[Document | None] = relationship()


class CalendarDay(Base):
    """Производственный календарь (из регламентированного календаря 1С). Хранятся все дни загруженного года."""

    __tablename__ = "calendar_days"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    working: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(64), default="1С")


class Task(Base):
    """Очередь задач для сервисов. Захват — SELECT … FOR UPDATE SKIP LOCKED, аренда с продлением."""

    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)  # ocr | extract | classify_act | fetch_letter | export_1c …
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued | running | done | failed | cancelled
    priority: Mapped[int] = mapped_column(Integer, default=100)  # меньше — раньше
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_by: Mapped[str] = mapped_column(String(128), default="")
    locked_by: Mapped[str] = mapped_column(String(128), default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Event(Base):
    """Журнал действий и лента изменений (курсор = id). before/after — для решений по полям."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # user | service | system
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    case_id: Mapped[int | None] = mapped_column(Integer, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    # Номер в ленте изменений: присваивается при чтении ленты только видимым (зафиксированным) строкам,
    # поэтому порядок ленты = порядок фиксации, и событие из долгой транзакции не проскакивает мимо курсора.
    feed_seq: Mapped[int | None] = mapped_column(BigInteger, index=True, unique=True)
