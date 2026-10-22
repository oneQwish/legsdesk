"""Аутентификация и права.

Люди входят доменной учёткой (AD/LDAP); роль определяется членством в группах AD.
Сервисы ходят с API-ключом: заголовок `Authorization: Bearer ldk_<prefix>_<secret>` или `X-API-Key`.
В БД хранится только sha256 секрета (секрет случайный, 256 бит — соль не нужна).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ApiKey, Service, User

COOKIE = "lawdesk_session"
ROLES = ("viewer", "lawyer", "admin")  # по возрастанию прав

# Области доступа сервисов
SCOPES = {
    "read": "Чтение дел, документов, сроков",
    "ingest": "Загрузка дел, наблюдений по полям, документов",
    "tasks": "Работа с очередью задач (захват, завершение)",
    "export": "Лента изменений и выгрузка для 1С",
    "calendar": "Загрузка производственного календаря",
}


@dataclass
class Principal:
    kind: str  # user | service
    name: str
    role: str = "viewer"
    scopes: set[str] = field(default_factory=set)
    service_id: int | None = None
    user_id: int | None = None

    def has_role(self, role: str) -> bool:
        return self.kind == "user" and ROLES.index(self.role) >= ROLES.index(role)


# --- LDAP --------------------------------------------------------------------------------------

class AuthError(Exception):
    def __init__(self, message: str, unavailable: bool = False):
        super().__init__(message)
        self.unavailable = unavailable  # сбой связи, а не неверные данные — не считается попыткой перебора


class LoginThrottle:
    """Защита от перебора паролей: после N неудач подряд для пары (логин, адрес) вход закрыт на 15 минут.
    Заодно бережёт учётные записи AD от блокировки чужими попытками. Хранится в памяти процесса."""

    WINDOW = timedelta(minutes=15)

    def __init__(self):
        self._fails: dict[tuple[str, str], list[datetime]] = {}

    def _recent(self, key: tuple[str, str]) -> list[datetime]:
        edge = datetime.now(UTC) - self.WINDOW
        recent = [t for t in self._fails.get(key, []) if t > edge]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return recent

    def blocked_for(self, login: str, ip: str) -> int:
        """Сколько минут ещё закрыт вход (0 — открыт)."""
        recent = self._recent((login, ip))
        if len(recent) < get_settings().login_max_failures:
            return 0
        left = recent[0] + self.WINDOW - datetime.now(UTC)
        return max(1, int(left.total_seconds() // 60) + 1)

    def failed(self, login: str, ip: str) -> None:
        if len(self._fails) > 10_000:  # не копить память при массовом переборе с разных адресов
            self._fails.clear()
        self._fails.setdefault((login, ip), []).append(datetime.now(UTC))

    def succeeded(self, login: str, ip: str) -> None:
        self._fails.pop((login, ip), None)


throttle = LoginThrottle()


def normalize_login(login: str) -> str:
    return login.strip().split("\\")[-1].split("@")[0].lower()


def ldap_authenticate(login: str, password: str) -> tuple[str, str, str]:
    """Проверяет пароль в AD и возвращает (ФИО, e-mail, роль). Роль — по группам."""
    import ldap3
    from ldap3.utils.conv import escape_filter_chars

    s = get_settings()
    if not password:
        raise AuthError("Пустой пароль")
    sam = login.split("\\")[-1].split("@")[0]
    server = ldap3.Server(s.ldap_url, get_info=ldap3.NONE, connect_timeout=5)
    exc = ldap3.core.exceptions
    try:
        conn = ldap3.Connection(server, user=f"{s.ldap_domain}\\{sam}", password=password,
                                authentication=ldap3.NTLM if s.ldap_url.startswith("ldap://") else ldap3.SIMPLE,
                                auto_bind=True, raise_exceptions=True, receive_timeout=10)
    except (exc.LDAPSocketOpenError, exc.LDAPSocketReceiveError, exc.LDAPSessionTerminatedByServerError) as e:
        # не путать с неверным паролем: иначе при недоступном контроллере «не пускает всех» без объяснения
        raise AuthError("Контроллер домена недоступен — сообщите администратору", unavailable=True) from e
    except exc.LDAPException as e:
        raise AuthError("Неверный логин или пароль") from e
    try:
        conn.search(s.ldap_base_dn, f"(sAMAccountName={escape_filter_chars(sam)})",
                    attributes=["displayName", "mail", "memberOf"])
        if not conn.entries:
            raise AuthError("Учётная запись не найдена")
        e = conn.entries[0]
        groups = [str(g) for g in (e.memberOf.values if "memberOf" in e else [])]
    finally:
        conn.unbind()

    def member(cn: str) -> bool:
        return any(g.upper().startswith(cn.upper() + ",") or g.upper() == cn.upper() for g in groups)

    if member(s.ldap_group_admin):
        role = "admin"
    elif member(s.ldap_group_lawyer):
        role = "lawyer"
    elif member(s.ldap_group_viewer):
        role = "viewer"
    else:
        raise AuthError("Нет доступа: учётная запись не входит в группы рабочего места")
    name = str(e.displayName) if "displayName" in e else sam
    mail = str(e.mail) if "mail" in e else ""
    return name, mail, role


def authenticate(db: Session, login: str, password: str) -> User:
    s = get_settings()
    login = normalize_login(login)
    if not login:
        raise AuthError("Пустой логин")
    if s.auth_mode == "dev":
        if not hmac.compare_digest(password, s.dev_password):
            raise AuthError("Неверный пароль (dev-режим)")
        full, mail, role = login, "", s.dev_role
    else:
        full, mail, role = ldap_authenticate(login, password)
    user = db.scalar(select(User).where(User.login == login))
    if user is None:
        user = User(login=login)
        db.add(user)
    if not user.active and user.id:
        raise AuthError("Учётная запись отключена в рабочем месте")
    user.full_name, user.email, user.role = full, mail, role
    user.last_login = datetime.now(UTC)
    db.commit()
    return user


def make_session_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(UTC) + timedelta(hours=s.session_hours)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, s.secret_key, algorithm="HS256")


# --- API-ключи ----------------------------------------------------------------------------------

def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def issue_api_key(db: Session, service: Service) -> str:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    db.add(ApiKey(service=service, prefix=prefix, secret_hash=_hash(secret)))
    db.flush()
    return f"ldk_{prefix}_{secret}"


def _service_from_key(db: Session, raw: str) -> Principal | None:
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != "ldk":
        return None
    key = db.scalar(select(ApiKey).where(ApiKey.prefix == parts[1], ApiKey.revoked_at.is_(None)))
    if key is None or not hmac.compare_digest(key.secret_hash, _hash(parts[2])) or not key.service.active:
        return None
    svc = key.service
    now = datetime.now(UTC)
    if svc.last_seen is None or now - svc.last_seen > timedelta(minutes=1):
        svc.last_seen = now
        db.commit()
    return Principal("service", svc.name, scopes=set(svc.scopes or []), service_id=svc.id)


# --- Зависимости FastAPI -----------------------------------------------------------------------

def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    raw = request.headers.get("x-api-key") or (auth[7:].strip() if auth.lower().startswith("bearer ") else "")
    if raw:
        p = _service_from_key(db, raw)
        if p is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный или отозванный API-ключ")
        return p
    token = request.cookies.get(COOKIE)
    if token:
        try:
            data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла") from None
        user = db.get(User, int(data["sub"]))
        if user and user.active:
            return Principal("user", user.login, role=user.role, user_id=user.id)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")


def require(*, role: str | None = None, scope: str | None = None):
    """Доступ для пользователя с ролью не ниже role ИЛИ для сервиса с областью scope.
    Если задано только одно из условий, другой тип субъекта не допускается."""

    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.kind == "user" and role and p.has_role(role):
            return p
        if p.kind == "service" and scope and scope in p.scopes:
            return p
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")

    return dep
