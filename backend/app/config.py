"""Настройки приложения. Все значения берутся из переменных окружения (префикс LAWDESK_) или .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAWDESK_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@localhost:5433/lawdesk"

    # Сессии пользователей (JWT в httpOnly-cookie)
    secret_key: str = "change-me"
    session_hours: int = 12
    cookie_secure: bool = False  # True за HTTPS

    # Вход: "ldap" (боевой) или "dev" (любой логин, пароль = dev_password; только для разработки)
    auth_mode: str = "ldap"
    dev_password: str = "dev"
    dev_role: str = "admin"

    # AD/LDAP
    ldap_url: str = "ldaps://dc.example.local"
    ldap_domain: str = "EXAMPLE"  # вход как DOMAIN\\login
    ldap_base_dn: str = "DC=example,DC=local"
    ldap_group_admin: str = "CN=Lawdesk-Admins"
    ldap_group_lawyer: str = "CN=Lawdesk-Lawyers"
    ldap_group_viewer: str = "CN=Lawdesk-Viewers"

    # Хранилище файлов документов: "local" (папка на сервере, по sha256) или "docflow" (1С:Документооборот)
    storage_backend: str = "local"
    storage_dir: str = "./storage"
    docflow_url: str = ""  # HTTP-сервис 1С:ДО, напр. https://1c.example.local/docflow/hs/lawdesk
    docflow_user: str = ""
    docflow_password: str = ""

    # Очередь задач
    task_default_lease_seconds: int = 600

    # Часовой пояс компании: от него считается «сегодня» для сроков и просрочек
    timezone: str = "Europe/Moscow"

    # Наибольший размер загружаемого файла документа, МБ (в nginx — client_max_body_size)
    max_upload_mb: int = 200

    # Защита входа: после стольких неудачных попыток подряд логин с этого адреса блокируется на 15 минут
    login_max_failures: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
