"""Настройки, которые нужны интерфейсу (раздел [interface] файла settings.toml)."""
from fastapi import APIRouter, Depends

from ..config import CLIENT_KEYS, get_settings
from ..security import Principal, require

router = APIRouter(prefix="/api/v1/settings", tags=["Служебное"])


@router.get("/client")
def client_settings(_: Principal = Depends(require(role="viewer"))):
    """Пороги и размеры для интерфейса: стопки «Стола», цели недели, лимиты списков."""
    s = get_settings()
    return {k: getattr(s, k) for k in CLIENT_KEYS}
