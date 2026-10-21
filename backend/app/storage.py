"""Хранилище файлов документов.

Целевое хранилище — 1С:Документооборот (решение 14.10). Пока ДО не подключён, работает локальная
папка на сервере с адресацией по sha256. Переключение — настройкой LAWDESK_STORAGE_BACKEND.

Контракт HTTP-сервиса ДО (его публикует специалист 1С, см. docs/integration-1c.md):
  POST {docflow_url}/files            multipart: file, meta (JSON) → {"id": "<ид карточки>"}
  GET  {docflow_url}/files/{id}       → содержимое файла
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import BinaryIO, Protocol

import httpx

from .config import get_settings


class StorageUnavailable(Exception):
    pass


class DocumentStore(Protocol):
    backend: str

    def put(self, sha256: str, data: bytes, filename: str, meta: dict) -> str: ...

    def open(self, ref: str) -> BinaryIO | bytes: ...


class LocalStore:
    backend = "local"

    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha[2:4] / sha

    def put(self, sha256: str, data: bytes, filename: str, meta: dict) -> str:
        p = self._path(sha256)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(p)
        return sha256

    def open(self, ref: str) -> BinaryIO:
        p = self._path(ref)
        if not p.exists():
            raise StorageUnavailable("Файл отсутствует в локальном хранилище")
        return p.open("rb")


class DocflowStore:
    """Адаптер 1С:Документооборот. Включается, когда ИТ опубликует HTTP-сервис."""

    backend = "docflow"

    def __init__(self, url: str, user: str, password: str):
        if not url:
            raise StorageUnavailable("1С:Документооборот не настроен (LAWDESK_DOCFLOW_URL)")
        self.url, self.auth = url.rstrip("/"), (user, password)

    def put(self, sha256: str, data: bytes, filename: str, meta: dict) -> str:
        r = httpx.post(f"{self.url}/files", auth=self.auth, timeout=120,
                       files={"file": (filename, data)}, data={"meta": json.dumps({**meta, "sha256": sha256}, ensure_ascii=False)})
        r.raise_for_status()
        return r.json()["id"]

    def open(self, ref: str) -> bytes:
        r = httpx.get(f"{self.url}/files/{ref}", auth=self.auth, timeout=120)
        if r.status_code == 404:
            raise StorageUnavailable("Файл не найден в 1С:Документооборот")
        r.raise_for_status()
        return r.content


def get_store(backend: str | None = None) -> DocumentStore:
    s = get_settings()
    backend = backend or s.storage_backend
    if backend == "local":
        return LocalStore(s.storage_dir)
    if backend == "docflow":
        return DocflowStore(s.docflow_url, s.docflow_user, s.docflow_password)
    raise StorageUnavailable(f"Хранилище «{backend}» недоступно из приложения")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
