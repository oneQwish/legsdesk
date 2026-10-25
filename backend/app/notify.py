"""Сервис уведомлений.

Уведомление всегда сохраняется в системе (колокольчик в интерфейсе). Дополнительные каналы — отправители
из CHANNELS; какие включены — [notify] channels в settings.toml. Сейчас готовы:
  inapp — только в системе (всегда);
  email — письмо через SMTP компании ([notify] smtp_*, пароль — LAWDESK_SMTP_PASSWORD), адрес — из AD.
Новый канал (мессенджер и т. п.) — класс с методом send(user, notification) в CHANNELS; остальной код не меняется.
"""
from __future__ import annotations

import logging
import smtplib
from collections.abc import Iterable
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Notification, User

log = logging.getLogger("lawdesk.notify")


class InApp:
    def send(self, user: User | None, n: Notification) -> None:  # запись в таблице уже и есть доставка
        return None


class Email:
    def send(self, user: User | None, n: Notification) -> None:
        s = get_settings()
        if not (user and user.email and s.smtp_host):
            return
        msg = EmailMessage()
        msg["Subject"] = f"Рабочее место юриста: {n.title}"
        msg["From"], msg["To"] = s.smtp_from, user.email
        link = f"{s.public_url.rstrip('/')}{n.link}" if s.public_url and n.link else ""
        msg.set_content(f"{n.title}\n\n{n.body}\n\n{link}".strip())
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                if s.smtp_tls:
                    smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        except Exception as e:  # noqa: BLE001 — сбой почты не должен ломать действие пользователя
            log.warning("письмо %s не отправлено: %s", user.email, e)


CHANNELS = {"inapp": InApp, "email": Email}


def notify(db: Session, logins: Iterable[str], kind: str, title: str, body: str = "", link: str = "",
           case_id: int | None = None, dedup: str | None = None, skip: str | None = None) -> int:
    """Уведомить пользователей (по логинам). dedup — одно и то же уведомление не придёт дважды.
    skip — кого не уведомлять (обычно автора действия). Возвращает число новых уведомлений."""
    targets = {x.strip().lower() for x in logins if x and x.strip()} - {(skip or "").lower()}
    if not targets:
        return 0
    channels = [CHANNELS[c]() for c in get_settings().notify_channels if c in CHANNELS and c != "inapp"]
    n_new = 0
    for login in sorted(targets):
        if dedup and db.scalar(select(Notification.id).where(Notification.login == login, Notification.dedup == dedup)):
            continue
        n = Notification(login=login, kind=kind, title=title[:256], body=body, link=link, case_id=case_id, dedup=dedup)
        db.add(n)
        n_new += 1
        if channels:
            user = db.scalar(select(User).where(User.login == login))
            for ch in channels:
                ch.send(user, n)
    db.flush()
    return n_new
