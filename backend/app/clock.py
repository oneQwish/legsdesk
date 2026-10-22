"""«Сегодня» и «сейчас» по часовому поясу компании (LAWDESK_TIMEZONE).

Сервер и база в контейнерах обычно живут по UTC: с 00:00 до 03:00 по Москве date.today() вернул бы
вчерашний день, и срок, истекающий сегодня, ещё не считался бы просроченным. Поэтому все расчёты
«относительно сегодня» берут дату отсюда, а не из date.today() или CURRENT_DATE базы.
"""
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from .config import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now() -> datetime:
    """Текущий момент (с часовым поясом UTC — так он хранится в базе)."""
    return datetime.now(UTC)


def today() -> date:
    return datetime.now(tz()).date()


def local(dt: datetime) -> datetime:
    return dt.astimezone(tz())
