"""Состояние резервных копий для страницы администратора.

Копии делает отдельный контейнер backup (папка backup/ в корне проекта). После каждой копии он
записывает итог в status.json; сервер приложения только читает этот файл (том backups смонтирован
в backend только для чтения). Путь к файлу — переменная окружения LAWDESK_BACKUP_STATUS_FILE.
"""

import json
import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from ..security import Principal, require

router = APIRouter(prefix="/api/v1/admin/backups", tags=["Администрирование"])

DEFAULT_STATUS_FILE = "/backups/status.json"
STALE_AFTER = timedelta(hours=26)  # копия раз в сутки + запас 2 часа


def _status_file() -> str:
    return os.environ.get("LAWDESK_BACKUP_STATUS_FILE") or DEFAULT_STATUS_FILE


def _parse_time(value) -> datetime | None:
    """Время из status.json (ISO 8601, например 2026-10-25T02:30:00+03:00). Без пояса считаем UTC."""
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


@router.get("")
def backup_status(_: Principal = Depends(require(role="admin"))):
    """Итог последней резервной копии. stale = true — копии давно не было (больше 26 часов) или нет файла."""
    path = _status_file()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"configured": False, "stale": True, "status_file": path,
                "error": "Файла состояния копий нет: контейнер backup не запущен или ещё не сделал ни одной копии"}
    except (OSError, ValueError) as e:  # нет прав, файл повреждён
        return {"configured": False, "stale": True, "status_file": path, "error": f"Файл состояния копий не читается: {e}"}
    if not isinstance(data, dict):
        return {"configured": False, "stale": True, "status_file": path, "error": "Файл состояния копий повреждён"}

    last_run = _parse_time(data.get("last_run"))
    data["configured"] = True
    data["stale"] = last_run is None or datetime.now(UTC) - last_run > STALE_AFTER
    return data
