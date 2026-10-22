import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles

from . import clock
from . import deadlines as dl
from .config import get_settings
from .db import SessionLocal, engine, init_db
from .routers import admin, auth, cases, conflicts, deadlines, documents, export, ingest, tasks, views, desk

DESCRIPTION = """
API рабочего места юриста. Люди входят доменной учёткой (cookie-сессия), сервисы системы
автоматизации — по API-ключу (`Authorization: Bearer ldk_…`), выданному в разделе «Сервисы».

Подключение сервиса — `docs/integration.md`; Python-клиент — `connectors/lawdesk_client.py`.
"""


def check_settings() -> None:
    """Отказаться стартовать с опасными настройками — понятным сообщением в журнале контейнера."""
    s = get_settings()
    if s.auth_mode not in ("ldap", "dev"):
        raise RuntimeError(f"LAWDESK_AUTH_MODE={s.auth_mode}: допустимо ldap или dev")
    if s.auth_mode == "dev" and s.cookie_secure:
        raise RuntimeError("LAWDESK_AUTH_MODE=dev (вход без пароля) запрещён на сервере с HTTPS — укажите ldap")
    if s.auth_mode != "dev" and (s.secret_key == "change-me" or len(s.secret_key) < 32):
        raise RuntimeError("Задайте LAWDESK_SECRET_KEY: случайная строка не короче 32 символов "
                           "(python3 -c \"import secrets;print(secrets.token_hex(32))\")")
    try:
        clock.tz()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"LAWDESK_TIMEZONE={s.timezone}: неизвестный часовой пояс (пример: Europe/Moscow)") from e


def daily_upkeep() -> int:
    """Регламентные действия «по дате»: закрыть прошедшие события (вступление в силу)."""
    with SessionLocal() as db:
        n = dl.close_passed_events(db, clock.today())
        db.commit()
        return n


async def upkeep_loop():
    while True:
        try:
            await asyncio.to_thread(daily_upkeep)
        except Exception:  # noqa: BLE001 — регламент не должен ронять сервер; повторится через час
            logging.getLogger("lawdesk").exception("регламентное действие не выполнено")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_settings()
    init_db()
    task = asyncio.create_task(upkeep_loop())
    yield
    task.cancel()


app = FastAPI(title="Рабочее место юриста", version="0.1.0", description=DESCRIPTION, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

for r in (auth, cases, conflicts, documents, deadlines, ingest, tasks, export, admin, views, desk):
    app.include_router(r.router)


@app.get("/api/health", tags=["Служебное"])
def health():
    """Для мониторинга: сервер отвечает и база доступна (иначе 503)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "база данных недоступна"}, status_code=503)
    return {"ok": True}


# Собранный фронтенд (если есть) отдаётся этим же процессом; в docker-compose его отдаёт nginx.
DIST = Path(get_settings().frontend_dist or Path(__file__).resolve().parents[2] / "frontend" / "dist")
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    ROOT = DIST.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (ROOT / path).resolve()
        # только файлы внутри dist: «..%2f» в адресе не должен выводить за пределы папки
        if path and f.is_file() and f.is_relative_to(ROOT):
            return FileResponse(f)
        return FileResponse(ROOT / "index.html")
