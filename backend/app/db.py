import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


MIGRATIONS = Path(os.environ.get("LAWDESK_MIGRATIONS_DIR", Path(__file__).resolve().parents[1] / "migrations"))
MIGRATION_LOCK = 774_210  # один процесс за раз, даже если запущено несколько экземпляров сервера


def init_db() -> None:
    """Создать недостающие таблицы и выполнить новые миграции из папки migrations (см. README.txt там)."""
    from . import models  # noqa: F401  регистрация таблиц

    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": MIGRATION_LOCK})
        Base.metadata.create_all(conn)
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations ("
                          "name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"))
        done = set(conn.scalars(text("SELECT name FROM schema_migrations")))
        for f in sorted(MIGRATIONS.glob("*.sql")) if MIGRATIONS.is_dir() else []:
            if f.name in done:
                continue
            with conn.begin_nested():
                try:
                    conn.exec_driver_sql(f.read_text(encoding="utf-8"))
                except Exception as e:
                    raise RuntimeError(f"Миграция {f.name} не выполнена: {e}") from e
                conn.execute(text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": f.name})
