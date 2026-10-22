from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .routers import admin, auth, cases, conflicts, deadlines, documents, export, ingest, tasks, views

DESCRIPTION = """
API рабочего места юриста. Люди входят доменной учёткой (cookie-сессия), сервисы системы
автоматизации — по API-ключу (`Authorization: Bearer ldk_…`), выданному в разделе «Сервисы».

Подключение сервиса — `docs/integration.md`; Python-клиент — `connectors/lawdesk_client.py`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if get_settings().secret_key == "change-me" and get_settings().auth_mode != "dev":
        raise RuntimeError("Задайте LAWDESK_SECRET_KEY (случайная строка) перед запуском в боевом режиме")
    yield


app = FastAPI(title="Рабочее место юриста", version="0.1.0", description=DESCRIPTION, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

for r in (auth, cases, conflicts, documents, deadlines, ingest, tasks, export, admin, views):
    app.include_router(r.router)


@app.get("/api/health", tags=["Служебное"])
def health():
    return {"ok": True}


# Собранный фронтенд (если есть) отдаётся этим же процессом; в docker-compose его отдаёт nginx.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
