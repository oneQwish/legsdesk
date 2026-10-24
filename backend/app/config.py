"""Настройки приложения.

Откуда берётся значение (каждое следующее главнее):
  1. умолчание — здесь, в коде;
  2. файл настроек backend/settings.toml (или путь из LAWDESK_SETTINGS_FILE) — для всех обычных настроек;
  3. переменная окружения LAWDESK_<ИМЯ> или строка в .env — для паролей, ключей и того, что отличается
     от сервера к серверу (адрес базы, режим входа на пробном компьютере).

Пароли и ключи (SECRETS) в файле настроек не принимаются: файл кладут в архивы и пересылают.
Опечатка в имени или разделе файла — сервер не стартует и подсказывает правильное имя.
`python -m app.cli настройки` показывает итоговые значения и откуда взято каждое.
"""
from __future__ import annotations

import difflib
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

SETTINGS_FILE = Path(__file__).resolve().parents[1] / "settings.toml"

# Только переменные окружения / .env — никогда в settings.toml
SECRETS = {"secret_key", "database_url", "docflow_password", "dev_password"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAWDESK_", env_file=".env", extra="ignore")

    # --- [server] ---------------------------------------------------------------------------
    timezone: str = "Europe/Moscow"
    frontend_dist: str = ""
    upkeep_interval_minutes: int = 60

    # --- секреты и адрес базы (только окружение) --------------------------------------------
    database_url: str = "postgresql+psycopg://postgres@localhost:5433/lawdesk"
    secret_key: str = "change-me"
    docflow_password: str = ""
    dev_password: str = "dev"

    # --- [auth] -----------------------------------------------------------------------------
    auth_mode: str = "ldap"
    session_hours: int = 12
    cookie_secure: bool = False
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    dev_role: str = "admin"
    dev_roles: str = ""

    # --- [ldap] -----------------------------------------------------------------------------
    ldap_url: str = "ldaps://dc.example.local"
    ldap_domain: str = "EXAMPLE"
    ldap_base_dn: str = "DC=example,DC=local"
    ldap_group_admin: str = "CN=Lawdesk-Admins"
    ldap_group_lawyer: str = "CN=Lawdesk-Lawyers"
    ldap_group_viewer: str = "CN=Lawdesk-Viewers"
    ldap_connect_timeout: int = 5
    ldap_receive_timeout: int = 10

    # --- [storage] --------------------------------------------------------------------------
    storage_backend: str = "local"
    storage_dir: str = "./storage"
    docflow_url: str = ""
    docflow_user: str = ""
    docflow_timeout: int = 120
    max_upload_mb: int = 200
    inline_mime: list[str] = ["application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp",
                              "image/tiff", "text/plain"]

    # --- [values] ---------------------------------------------------------------------------
    source_trust: list[str] = ["ручной", "письмо", "1С", "отчёт", "OCR"]

    # --- [deadlines] ------------------------------------------------------------------------
    soon_days: int = 7
    calendar_min_nonworking: int = 100
    calendar_max_nonworking: int = 140
    fallback_holidays: list[str] = ["01-01", "01-02", "01-03", "01-04", "01-05", "01-06", "01-07", "01-08",
                                    "02-23", "03-08", "05-01", "05-09", "06-12", "11-04"]

    # --- [limits] ---------------------------------------------------------------------------
    ingest_max_batch: int = 1000
    page_size_max: int = 500
    conflicts_page_max: int = 200
    journal_page_max: int = 1000
    feed_limit_max: int = 5000
    deadlines_limit_max: int = 5000
    case_events_limit: int = 500
    facet_limit: int = 200
    feed_sequence_batch: int = 50000

    # --- [tasks] ----------------------------------------------------------------------------
    task_default_lease_seconds: int = 600

    # --- [interface] (передаётся в браузер: GET /api/v1/settings/client) ----------------------
    desk_strip_days: int = 14
    desk_strip_max_days: int = 62
    desk_hot_days: int = 3
    desk_week_days: int = 10
    desk_pile_size: int = 60
    deadlines_page_limit: int = 2000
    deadlines_group_limit: int = 150
    goal_conflicts: int = 50
    goal_deadlines: int = 20
    goal_documents: int = 20

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings,
                                   file_secret_settings):
        # порядок = приоритет: окружение и .env главнее файла настроек
        return init_settings, env_settings, dotenv_settings, TomlSource(settings_cls), file_secret_settings


# В каком разделе файла лежит каждая настройка (раздел — только для удобства чтения файла)
SECTIONS: dict[str, list[str]] = {
    "server": ["timezone", "frontend_dist", "upkeep_interval_minutes"],
    "auth": ["auth_mode", "session_hours", "cookie_secure", "login_max_failures", "login_lockout_minutes",
             "dev_role", "dev_roles"],
    "ldap": ["ldap_url", "ldap_domain", "ldap_base_dn", "ldap_group_admin", "ldap_group_lawyer", "ldap_group_viewer",
             "ldap_connect_timeout", "ldap_receive_timeout"],
    "storage": ["storage_backend", "storage_dir", "docflow_url", "docflow_user", "docflow_timeout", "max_upload_mb",
                "inline_mime"],
    "values": ["source_trust"],
    "deadlines": ["soon_days", "calendar_min_nonworking", "calendar_max_nonworking", "fallback_holidays"],
    "limits": ["ingest_max_batch", "page_size_max", "conflicts_page_max", "journal_page_max", "feed_limit_max",
               "deadlines_limit_max", "case_events_limit", "facet_limit", "feed_sequence_batch"],
    "tasks": ["task_default_lease_seconds"],
    "interface": ["desk_strip_days", "desk_strip_max_days", "desk_hot_days", "desk_week_days", "desk_pile_size",
                  "deadlines_page_limit", "deadlines_group_limit", "goal_conflicts", "goal_deadlines", "goal_documents"],
}
CLIENT_KEYS = SECTIONS["interface"] + ["soon_days", "timezone"]


class SettingsFileError(RuntimeError):
    """Ошибка в файле настроек — текст для человека."""


def settings_path() -> Path:
    return Path(os.environ.get("LAWDESK_SETTINGS_FILE") or SETTINGS_FILE)


def read_settings_file(path: Path | None = None) -> dict[str, Any]:
    """Файл настроек → плоский словарь {имя: значение}. Нет файла — пустой словарь (действуют умолчания)."""
    path = path or settings_path()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SettingsFileError(f"{path}: ошибка записи — {e}. Частые причины: нет кавычек вокруг текста, "
                                f"обратная косая черта в пути (пишите /)") from None
    owner = {k: s for s, keys in SECTIONS.items() for k in keys}
    out: dict[str, Any] = {}
    for section, body in data.items():
        if section not in SECTIONS:
            hint = difflib.get_close_matches(section, SECTIONS, n=1)
            raise SettingsFileError(f"{path}: неизвестный раздел [{section}]"
                                    + (f" — может быть, [{hint[0]}]?" if hint else f". Разделы: {', '.join(SECTIONS)}"))
        if not isinstance(body, dict):
            raise SettingsFileError(f"{path}: «{section}» должен быть разделом [{section}], а не значением")
        for key, value in body.items():
            if key in SECRETS:
                raise SettingsFileError(f"{path}: [{section}] {key} — секрет, в файле настроек его хранить нельзя. "
                                        f"Задайте переменную окружения LAWDESK_{key.upper()} (файл .env)")
            if key not in owner:
                hint = difflib.get_close_matches(key, owner, n=1)
                raise SettingsFileError(f"{path}: [{section}] неизвестная настройка «{key}»"
                                        + (f" — может быть, «{hint[0]}»?" if hint else ""))
            if owner[key] != section:
                raise SettingsFileError(f"{path}: «{key}» относится к разделу [{owner[key]}], а записана в [{section}]")
            out[key] = value
    return out


class TomlSource(PydanticBaseSettingsSource):
    def get_field_value(self, field, field_name):  # не используется: значения отдаёт __call__
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return read_settings_file()


def describe_sources() -> dict[str, str]:
    """Откуда взято каждое значение: умолчание, файл или окружение (для команды «настройки»)."""
    file_keys = set(read_settings_file())
    env_keys = {k[len("LAWDESK_"):].lower() for k in os.environ if k.startswith("LAWDESK_")}
    dotenv = Path(".env")
    if dotenv.exists():
        env_keys |= {line.split("=", 1)[0].strip()[len("LAWDESK_"):].lower() for line in dotenv.read_text().splitlines()
                     if line.strip().startswith("LAWDESK_") and "=" in line}
    return {k: "окружение" if k in env_keys else "файл" if k in file_keys else "умолчание"
            for k in Settings.model_fields}


def problems(s: Settings) -> list[str]:
    """Смысловая проверка значений (типы проверяет pydantic). Пустой список — всё в порядке."""
    out = []
    if s.auth_mode not in ("ldap", "dev"):
        out.append(f"[auth] auth_mode = «{s.auth_mode}»: допустимо ldap или dev")
    if s.storage_backend not in ("local", "docflow"):
        out.append(f"[storage] storage_backend = «{s.storage_backend}»: допустимо local или docflow")
    for name in Settings.model_fields:
        v = getattr(s, name)
        if isinstance(v, int) and not isinstance(v, bool) and v <= 0:
            out.append(f"{name} = {v}: нужно положительное число")
    for h in s.fallback_holidays:
        try:
            m, d = (int(x) for x in h.split("-"))
            assert 1 <= m <= 12 and 1 <= d <= 31
        except (ValueError, AssertionError):
            out.append(f"[deadlines] fallback_holidays: «{h}» — нужен вид ММ-ДД, например 05-09")
    if s.calendar_min_nonworking >= s.calendar_max_nonworking:
        out.append("[deadlines] calendar_min_nonworking должно быть меньше calendar_max_nonworking")
    if s.desk_strip_days > s.desk_strip_max_days:
        out.append("[interface] desk_strip_days больше desk_strip_max_days")
    if not s.source_trust:
        out.append("[values] source_trust пуст — укажите источники от самого надёжного к наименее")
    return out


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']} (получено «{x.get('input')}»)" for x in e.errors())
        raise SettingsFileError(f"неверное значение настройки — {problems}. Проверьте {settings_path()} "
                                f"и переменные LAWDESK_…") from None
