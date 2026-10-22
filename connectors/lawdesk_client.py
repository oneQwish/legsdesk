"""Клиент API рабочего места юриста для сервисов системы автоматизации.

Только стандартная библиотека Python (urllib) — можно класть рядом с любым скриптом конвейера
(archive_ocr.py, llm_extract.py, sot/*.py, для_рабочего_пк/*.py) без установки пакетов.

    from lawdesk_client import Lawdesk
    ld = Lawdesk("https://lawdesk.example.local", key=os.environ["LAWDESK_KEY"])
    ld.cases([{"uid": "50RS0010-01-2025-000287-27", "court_code": "000000123", "case_number": "2-1459/2025"}])
    ld.observations([{"uid": "...", "field": "amount_debt", "source": "OCR", "value": "141611.96",
                      "document_sha256": "...", "page": 4, "quote": "взыскать ... 141 611,96 руб."}])

    # Рабочий цикл сервиса очереди: исключение в обработчике → задача помечается fail и уйдёт на повтор
    def handle(task):
        pdf = task.payload["path"]
        ...
        return {"pages": 12}
    ld.run(handle, ["ocr"])
"""
from __future__ import annotations

import json
import mimetypes
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path


class LawdeskError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


# Паузы между повторами при временных сбоях (перезапуск сервера, обрыв сети): ~1,5 минуты в сумме
RETRY_DELAYS = (2, 5, 10, 20, 40)
RETRY_STATUS = {429, 500, 502, 503, 504}


def _ssl_problem(e: BaseException) -> bool:
    return isinstance(getattr(e, "reason", e), ssl.SSLError)


def read_cursor(path: str | Path, default: int = 0) -> int:
    """Курсор ленты из файла. Пустой или испорченный файл — ошибка, а не «начать с нуля»:
    иначе вся история изменений молча ушла бы во внешнюю систему повторно."""
    p = Path(path)
    if not p.exists():
        return default
    text = p.read_text(encoding="utf-8").strip()
    if not text.isdigit():
        raise ValueError(f"файл курсора {p} пустой или испорчен («{text[:20]}»). Впишите в него номер последнего "
                         f"выгруженного события (см. журнал прошлого запуска) или удалите файл, чтобы начать с начала")
    return int(text)


def write_cursor(path: str | Path, value: int) -> None:
    """Записать курсор атомарно: обрыв посреди записи не оставит пустой файл."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(value))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


class Lawdesk:
    def __init__(self, base_url: str, key: str, timeout: float = 180, cafile: str | None = None, batch: int = 500):
        self.base = base_url.rstrip("/")
        self.key, self.timeout, self.batch = key, timeout, batch
        self.ctx = ssl.create_default_context(cafile=cafile) if cafile else None

    # --- транспорт ----------------------------------------------------------------------------

    def request(self, method: str, path: str, body=None, params: dict | None = None,
                data: bytes | None = None, content_type: str | None = None, retries: int | None = None):
        url = self.base + path + ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}) if params else "")
        if body is not None:
            data, content_type = json.dumps(body, ensure_ascii=False, default=str).encode(), "application/json"
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        # повторы безопасны: приём данных идемпотентен (повторная отправка ничего не дублирует)
        delays = RETRY_DELAYS if retries is None else RETRY_DELAYS[:retries]
        for attempt in range(len(delays) + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                    raw = r.read()
                    if r.headers.get_content_type() == "application/json":
                        return json.loads(raw) if raw else None
                    return raw
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                try:
                    detail = json.loads(detail).get("detail", detail)
                except (ValueError, AttributeError):
                    pass
                if e.code in RETRY_STATUS and attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise LawdeskError(e.code, detail) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if _ssl_problem(e):  # сертификат не изменится от повтора
                    raise urllib.error.URLError(f"{getattr(e, 'reason', e)} — сертификат сервера не прошёл проверку; "
                                                f"укажите файл корневого сертификата компании: cafile = \"…\"") from None
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise

    def _batched(self, path: str, items: Iterable[dict]) -> list[dict]:
        """Отправка пакетами. Результат — по одному на элемент, в том же порядке, что items."""
        out, chunk = [], []
        for it in items:
            chunk.append(it)
            if len(chunk) >= self.batch:
                out += self._send(path, chunk)
                chunk = []
        if chunk:
            out += self._send(path, chunk)
        return out

    def _send(self, path: str, chunk: list[dict]) -> list[dict]:
        """Сервер проверяет формат всего пакета сразу: одна строка с неверной датой даёт 422 на весь пакет.
        Тогда пакет делится пополам, пока плохие элементы не останутся по одному — остальные проходят."""
        try:
            return self.request("POST", path, chunk)
        except LawdeskError as e:
            if e.status != 422:
                raise
            if len(chunk) == 1:
                return [{"index": 0, "ok": False, "error": _format_422(e.detail)}]
            mid = len(chunk) // 2
            return self._send(path, chunk[:mid]) + self._send(path, chunk[mid:])

    # --- приём данных -------------------------------------------------------------------------

    def cases(self, items: Iterable[dict]) -> list[dict]:
        return self._batched("/api/v1/ingest/cases", items)

    def observations(self, items: Iterable[dict]) -> list[dict]:
        return self._batched("/api/v1/ingest/observations", items)

    def documents(self, items: Iterable[dict]) -> list[dict]:
        return self._batched("/api/v1/ingest/documents", items)

    def upload(self, path: str | Path, meta: dict | None = None, signature: str | Path | None = None) -> dict:
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []

        def field(name: str, value: bytes, filename: str | None = None, ctype: str = "text/plain; charset=utf-8"):
            # filename — в UTF-8 как есть (так делают браузеры; filename*= серверный парсер не понимает)
            safe = filename.replace('"', "'").replace("\r", "").replace("\n", "") if filename else ""
            disp = f'form-data; name="{name}"' + (f'; filename="{safe}"' if filename else "")
            parts.append(f"--{boundary}\r\nContent-Disposition: {disp}\r\nContent-Type: {ctype}\r\n\r\n".encode() + value + b"\r\n")

        p = Path(path)
        field("file", p.read_bytes(), p.name, mimetypes.guess_type(p.name)[0] or "application/octet-stream")
        field("meta", json.dumps(meta or {}, ensure_ascii=False, default=str).encode())
        if signature:
            s = Path(signature)
            field("signature", s.read_bytes(), s.name, "application/octet-stream")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        return self.request("POST", "/api/v1/ingest/documents/upload", data=body,
                            content_type=f"multipart/form-data; boundary={boundary}")

    def calendar(self, year: int, nonworking: list[str], source: str = "1С") -> dict:
        return self.request("PUT", "/api/v1/calendar", {"year": year, "nonworking": nonworking, "source": source})

    # --- чтение -------------------------------------------------------------------------------

    def get_case(self, case_id: int) -> dict:
        return self.request("GET", f"/api/v1/cases/{case_id}")

    def find_cases(self, q: str, **filters) -> dict:
        return self.request("GET", "/api/v1/cases", params={"q": q, **filters})

    def changes(self, after: int = 0, actions: str | None = None, limit: int = 500) -> dict:
        return self.request("GET", "/api/v1/changes", params={"after": after, "actions": actions, "limit": limit})

    def follow_changes(self, cursor_file: str | Path, actions: str | None = None) -> Iterator[dict]:
        """Читать ленту с сохранённого курсора; курсор пишется в файл после каждой порции."""
        cursor = read_cursor(cursor_file)
        while True:
            page = self.changes(cursor, actions)
            yield from page["items"]
            if page["next_cursor"] == cursor:
                return
            cursor = page["next_cursor"]
            write_cursor(cursor_file, cursor)

    # --- очередь задач ------------------------------------------------------------------------

    def create_task(self, type: str, payload: dict | None = None, **kw) -> dict:
        return self.request("POST", "/api/v1/tasks", {"type": type, "payload": payload or {}, **kw})

    def claim(self, types: list[str] | None = None, limit: int = 1, lease_seconds: int | None = None) -> list["Task"]:
        rows = self.request("POST", "/api/v1/tasks/claim", {"types": types or [], "limit": limit, "lease_seconds": lease_seconds})
        return [Task(self, r) for r in rows]

    def run(self, handler: Callable[["Task"], dict | None], types: list[str] | None = None, idle_sleep: float = 10,
            lease_seconds: int | None = None, stop_when_empty: bool = False) -> int:
        """Цикл обработки задач: handler(task) → результат (dict) или None.
        Исключение в handler → fail с повтором. Возвращает число обработанных задач."""
        n = 0
        while True:
            tasks = self.claim(types, 1, lease_seconds)
            if not tasks:
                if stop_when_empty:
                    return n
                time.sleep(idle_sleep)
                continue
            t = tasks[0]
            try:
                result = handler(t)
            except Exception as e:  # noqa: BLE001 — ошибку задачи сообщаем в очередь
                if not t.finished:
                    t.fail(f"{type(e).__name__}: {e}")
            else:
                if not t.finished:
                    t.done(result or {})
            n += 1


def _format_422(detail) -> str:
    """Ошибки проверки формата → «поле act_date: Input should be a valid date (получено «01.02.2027»)»."""
    if not isinstance(detail, list):
        return str(detail)
    parts = []
    for d in detail:
        loc = [str(x) for x in d.get("loc", []) if x != "body" and not isinstance(x, int)]
        got = f" (получено «{d['input']}»)" if "input" in d and not isinstance(d["input"], (dict, list)) else ""
        parts.append(f"поле {'.'.join(loc) or '?'}: {d.get('msg', '')}{got}")
    return "; ".join(parts)


class Task:
    def __init__(self, client: Lawdesk, row: dict):
        self.client, self.row, self.finished = client, row, False
        self.id, self.type, self.payload = row["id"], row["type"], row["payload"]

    def heartbeat(self, lease_seconds: int | None = None) -> None:
        self.client.request("POST", f"/api/v1/tasks/{self.id}/heartbeat", {"lease_seconds": lease_seconds})

    def done(self, result: dict | None = None) -> None:
        self.client.request("POST", f"/api/v1/tasks/{self.id}/complete", {"result": result or {}})
        self.finished = True

    def fail(self, error: str, retry: bool = True, retry_in_seconds: int = 60) -> None:
        self.client.request("POST", f"/api/v1/tasks/{self.id}/fail",
                            {"error": error, "retry": retry, "retry_in_seconds": retry_in_seconds})
        self.finished = True
