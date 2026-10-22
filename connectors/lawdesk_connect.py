"""Универсальный коннектор рабочего места юриста.

Один файл, только стандартная библиотека Python 3.11+. Что и откуда брать, описывается в файле
настроек (.toml) — программировать не нужно. Подробно: docs/коннекторы.md.

    python lawdesk_connect.py проверить  настройки.toml      — проверка без отправки (что прочитано, во что превратится)
    python lawdesk_connect.py запустить  настройки.toml      — выполнить
    python lawdesk_connect.py шаблон     csv > мой.toml      — заготовка настроек для типа источника
    python lawdesk_connect.py поля       настройки.toml      — список полей дела, которые принимает рабочее место

(Те же команды по-английски: check, run, template, fields.)

Направления:
  in  — данные ИЗ внешней системы В рабочее место: дела, значения полей, документы, производственный календарь;
  out — изменения ИЗ рабочего места НАРУЖУ: решения юристов и др. события → файл или HTTP-сервис другой системы.

Источники (in):  csv, xlsx, json, folder (папка с файлами), http_json, odata (в т.ч. 1С), sqlite, sql.
Приёмники (out): csv, json, http.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import fnmatch
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lawdesk_client import Lawdesk, LawdeskError  # noqa: E402

VERSION = "1.0"
log = logging.getLogger("lawdesk")


class ConfigError(Exception):
    """Ошибка в файле настроек — сообщение для человека, без трассировки."""


class LinkError(Exception):
    """Внешняя система недоступна или ответила ошибкой (сеть, пароль, адрес)."""


# =============================================================================================
# Шаблоны значений: "{Колонка}", "{Колонка|фильтр}", "{Колонка|фильтр:параметр}", текст вокруг.
# =============================================================================================

TEMPLATE_RE = re.compile(r"\{([^{}|]+)((?:\|[^{}|]+)*)\}")


def _money(v: str) -> str:
    s = re.sub(r"[\s ]", "", str(v)).replace(",", ".")
    s = re.sub(r"(руб\.?|₽|р\.)$", "", s, flags=re.I)
    if not s:
        return ""
    try:
        return f"{float(s):.2f}"
    except ValueError:
        raise ValueError(f"не похоже на сумму: «{v}»") from None


def _date(v: str, fmt: str | None) -> str:
    v = str(v).strip()
    if not v:
        return ""
    if fmt:
        return dt.datetime.strptime(v, fmt).date().isoformat()
    for f in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y%m%d"):
        try:
            d = dt.datetime.strptime(v[:19] if "T" in v else v, f).date()
            return "" if d.year < 1900 else d.isoformat()  # 0001-01-01 — «пустая дата» 1С
        except ValueError:
            continue
    raise ValueError(f"не похоже на дату: «{v}» (укажите формат: |date:%d.%m.%Y)")


def apply_filter(value: str, name: str, arg: str | None, maps: dict) -> str:
    """Фильтры шаблонов. Список — в docs/коннекторы.md, раздел «Фильтры»."""
    v = "" if value is None else str(value)
    match name:
        case "trim": return v.strip()
        case "upper": return v.upper()
        case "lower": return v.lower()
        case "money": return _money(v)
        case "kopecks": return f"{int(float(v or 0)) / 100:.2f}" if v.strip() else ""
        case "int": return str(int(float(v))) if v.strip() else ""
        case "date": return _date(v, arg)
        case "digits": return re.sub(r"\D", "", v)
        case "default": return v if v.strip() else (arg or "")
        case "bool": return "true" if v.strip().lower() in ("1", "да", "истина", "true", "yes", "+") else "false"
        case "first": return re.split(r"[;,\n]", v)[0].strip()
        case "replace":
            a, _, b = (arg or "").partition("=>")
            return v.replace(a, b)
        case "map":
            table = maps.get(arg or "")
            if table is None:
                raise ConfigError(f"фильтр |map:{arg} — нет таблицы [maps.{arg}] в настройках")
            return str(table.get(v, table.get("*", v)))
        case _:
            raise ConfigError(f"неизвестный фильтр |{name}. Доступны: trim, upper, lower, money, kopecks, int, date, digits, default, bool, first, replace, map")


def render(template, row: dict, maps: dict, strict: bool = True) -> str | None:
    """Подставить значения строки в шаблон. Число/булево в настройках — как есть.
    strict=False (выгрузка наружу): нет значения — пустая строка вместо ошибки."""
    if template is None:
        return None
    if not isinstance(template, str):
        return str(template).lower() if isinstance(template, bool) else str(template)

    def sub(m: re.Match) -> str:
        key = m.group(1).strip()
        filters = [x for x in m.group(2).split("|") if x]
        try:
            val = lookup(row, key)
        except KeyError:
            # нет колонки: допустимо, только если задано значение по умолчанию (|default:…)
            if strict and not any(f.split(":")[0].strip() == "default" for f in filters):
                raise
            val = ""
        for f in filters:
            name, _, arg = f.partition(":")
            val = apply_filter(val, name.strip(), arg or None, maps)
        return "" if val is None else str(val)

    return TEMPLATE_RE.sub(sub, template).strip()


def lookup(row: dict, key: str):
    """Значение колонки; «a.b.c» — вложенные поля JSON; регистр и «ё» в имени колонки не важны."""
    if key in row:
        return row[key]
    cur = row
    for part in key.split("."):
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
                continue
            low = {_norm_key(k): v for k, v in cur.items()}
            if _norm_key(part) in low:
                cur = low[_norm_key(part)]
                continue
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
            continue
        raise KeyError(key)
    return cur


def _norm_key(k: str) -> str:
    return str(k).strip().lower().replace("ё", "е")


def template_columns(template) -> list[str]:
    """Колонки, обязательные в источнике (с |default колонка может отсутствовать)."""
    if not isinstance(template, str):
        return []
    return [m.group(1).strip() for m in TEMPLATE_RE.finditer(template) if "|default" not in m.group(2)]


# =============================================================================================
# Источники: каждый возвращает строки — словари «колонка → значение»
# =============================================================================================

def _auth_header(cfg: dict) -> dict:
    user = cfg.get("user")
    if not user:
        return {}
    pwd = os.environ.get(cfg.get("password_env", ""), "") if cfg.get("password_env") else cfg.get("password", "")
    if not pwd and cfg.get("password_env"):
        raise ConfigError(f"не задана переменная окружения {cfg['password_env']} с паролем для {cfg.get('url')}")
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()}


def _http_json(url: str, cfg: dict, method: str = "GET", body=None) -> object:
    headers = {"Accept": "application/json", **_auth_header(cfg), **cfg.get("headers", {})}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, default=str).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 120)) as r:
            raw = r.read()
            return json.loads(raw.decode(r.headers.get_content_charset() or "utf-8")) if raw else None
    except urllib.error.HTTPError as e:
        hint = {401: " (неверный логин/пароль)", 403: " (у пользователя нет прав)", 404: " (неверный адрес или имя объекта)"}.get(e.code, "")
        raise LinkError(f"{method} {url} → HTTP {e.code}{hint}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    except urllib.error.URLError as e:
        raise LinkError(f"{method} {url} — нет связи: {e.reason}") from None


def _items(data, path: str | None):
    if path:
        for part in path.split("."):
            data = data.get(part, []) if isinstance(data, dict) else []
    if isinstance(data, dict):
        data = [data]
    return data or []


def _resolve(base: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (base / path)


def read_csv(cfg: dict, base: Path):
    path = _resolve(base, cfg["path"])
    enc = cfg.get("encoding", "utf-8-sig")
    with open(path, encoding=enc, newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delim = cfg.get("delimiter") or (";" if sample.count(";") >= sample.count(",") else ",")
        yield from csv.DictReader(f, delimiter=delim)


def read_xlsx(cfg: dict, base: Path):
    """Чтение .xlsx без сторонних библиотек: значения ячеек как текст, первая строка — заголовки."""
    path = _resolve(base, cfg["path"])
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        sheets = [(s.get("name"), rels[s.get(f"{{{ns['r']}}}id")]) for s in wb.find("m:sheets", ns)]
        want = cfg.get("sheet")
        chosen = next((t for n, t in sheets if n == want), None) if want else sheets[0][1]
        if chosen is None:
            raise ConfigError(f"в книге нет листа «{want}». Есть: {', '.join(n for n, _ in sheets)}")
        target = chosen.lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(z.read(target))
    date_cols = set(cfg.get("date_columns", []))
    header: list[str] = []
    skip = int(cfg.get("skip_rows", 0))
    for i, row in enumerate(root.iter(f"{{{ns['m']}}}row")):
        if i < skip:
            continue
        cells: dict[int, str] = {}
        for c in row.findall("m:c", ns):
            ref = c.get("r", "")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0):
                col = col * 26 + ord(ch) - 64
            v = c.find("m:v", ns)
            t = c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            else:
                val = v.text if v is not None else ""
            cells[col - 1] = val or ""
        values = [cells.get(k, "") for k in range(max(cells) + 1)] if cells else []
        if not header:
            header = [h.strip() for h in values]
            continue
        rec = {h: (values[k] if k < len(values) else "") for k, h in enumerate(header) if h}
        for h in date_cols:  # даты Excel хранятся числом дней от 30.12.1899
            if re.fullmatch(r"\d+(\.\d+)?", rec.get(h, "") or ""):
                rec[h] = (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(rec[h])))).isoformat()
        if any(str(x).strip() for x in rec.values()):
            yield rec


def read_json(cfg: dict, base: Path):
    path = _resolve(base, cfg["path"])
    with open(path, encoding=cfg.get("encoding", "utf-8-sig")) as f:
        yield from _items(json.load(f), cfg.get("items_path"))


def read_folder(cfg: dict, base: Path):
    """Файлы папки: имя, путь, размер, sha256; рядом лежащий «файл.json» добавляет свои поля."""
    root = _resolve(base, cfg["path"])
    pattern = cfg.get("pattern", "*")
    files = root.rglob("*") if cfg.get("recursive", True) else root.glob("*")
    for p in sorted(files):
        if not p.is_file() or p.suffix.lower() == ".json" or not fnmatch.fnmatch(p.name.lower(), pattern.lower()):
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        rec = {"файл": p.name, "путь": str(p), "папка": p.parent.name, "имя": p.stem,
               "расширение": p.suffix.lower().lstrip("."), "размер": p.stat().st_size, "sha256": h.hexdigest()}
        side = p.with_suffix(p.suffix + ".json") if p.with_suffix(p.suffix + ".json").exists() else p.with_suffix(".json")
        if side.exists():
            with open(side, encoding="utf-8-sig") as f:
                rec.update(json.load(f))
        yield rec


def read_http_json(cfg: dict, base: Path):
    """GET JSON; постраничность: next_path (ссылка на следующую страницу в ответе) или page_size (+ параметры)."""
    url = cfg["url"]
    params = dict(cfg.get("params", {}))
    page_size = cfg.get("page_size")
    offset = 0
    while url:
        full = url + (("&" if "?" in url else "?") + urllib.parse.urlencode(params) if params else "")
        data = _http_json(full, cfg)
        items = _items(data, cfg.get("items_path"))
        yield from items
        if cfg.get("next_path"):
            nxt = data
            for part in cfg["next_path"].split("."):
                nxt = nxt.get(part) if isinstance(nxt, dict) else None
            url, params = (nxt, {}) if nxt else (None, {})
        elif page_size and len(items) >= page_size:
            offset += page_size
            params[cfg.get("offset_param", "offset")] = offset
            params[cfg.get("limit_param", "limit")] = page_size
        else:
            url = None


def read_odata(cfg: dict, base: Path):
    """OData (стандартный интерфейс 1С: …/odata/standard.odata). Пакетами по page_size через $top/$skip."""
    root = cfg["url"].rstrip("/")
    entity = cfg["entity"]
    page = int(cfg.get("page_size", 1000))
    skip = 0
    while True:
        q = {"$format": "json", "$top": page, "$skip": skip}
        for k in ("select", "filter", "expand", "orderby"):
            if cfg.get(k):
                q[f"${k}"] = cfg[k]
        url = f"{root}/{urllib.parse.quote(entity)}?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
        items = _items(_http_json(url, cfg), "value")
        yield from items
        if len(items) < page:
            return
        skip += page


def read_sqlite(cfg: dict, base: Path):
    path = _resolve(base, cfg["path"])
    if not path.exists():
        raise ConfigError(f"нет файла базы {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # только чтение
    con.row_factory = sqlite3.Row
    try:
        for r in con.execute(cfg["query"]):
            yield dict(r)
    finally:
        con.close()


def read_sql(cfg: dict, base: Path):
    """Любая СУБД через SQLAlchemy (PostgreSQL, MS SQL, …): pip install sqlalchemy + драйвер."""
    try:
        import sqlalchemy as sa
    except ImportError:
        raise ConfigError("для type = \"sql\" установите: pip install sqlalchemy и драйвер вашей СУБД (см. docs/коннекторы.md)") from None
    url = os.environ.get(cfg["url_env"]) if cfg.get("url_env") else cfg.get("url")
    if not url:
        raise ConfigError("для type = \"sql\" укажите url или url_env (имя переменной окружения со строкой подключения)")
    eng = sa.create_engine(url)
    with eng.connect() as c:
        for r in c.execute(sa.text(cfg["query"])).mappings():
            yield dict(r)


SOURCES = {"csv": read_csv, "xlsx": read_xlsx, "json": read_json, "folder": read_folder,
           "http_json": read_http_json, "odata": read_odata, "sqlite": read_sqlite, "sql": read_sql}
REQUIRED = {"csv": ["path"], "xlsx": ["path"], "json": ["path"], "folder": ["path"], "http_json": ["url"],
            "odata": ["url", "entity"], "sqlite": ["path", "query"], "sql": ["query"]}


def read_rows(src: dict, base: Path, limit: int | None = None):
    t = src.get("type")
    if t not in SOURCES:
        raise ConfigError(f"[source] type = «{t}» — неизвестный тип. Доступны: {', '.join(SOURCES)}")
    miss = [k for k in REQUIRED[t] if not src.get(k)]
    if miss:
        raise ConfigError(f"[source] для type = \"{t}\" нужно указать: {', '.join(miss)}")
    flt = src.get("only_if", [])
    n = 0
    for row in SOURCES[t](src, base):
        if not all(_row_matches(row, f) for f in flt):
            continue
        yield row
        n += 1
        if limit and n >= limit:
            return


def _row_matches(row: dict, f: dict) -> bool:
    try:
        v = str(lookup(row, f["column"]) or "").strip()
    except KeyError:
        raise ConfigError(f"[[source.only_if]] — в источнике нет колонки «{f['column']}»") from None
    if "in" in f and v not in [str(x) for x in f["in"]]:
        return False
    if "not_in" in f and v in [str(x) for x in f["not_in"]]:
        return False
    if f.get("not_empty") and not v:
        return False
    return True


# =============================================================================================
# Направление «in»: строки источника → дела, наблюдения, документы, календарь
# =============================================================================================

CASE_KEYS = ["uid", "court_code", "court_name", "case_number", "legal_entity", "complex", "building", "flat",
             "contract_no", "plaintiffs", "subject", "stage", "status", "outcome", "responsible", "appeal_flag"]
DOC_KEYS = ["sha256", "filename", "mime", "kind", "act_type", "instance", "act_date", "motivated_date", "outcome",
            "track_no", "docflow_id", "storage_backend", "storage_ref", "text", "text_source"]


def _case_ref(case: dict) -> dict:
    if case.get("uid"):
        return {"uid": case["uid"]}
    return {"court_code": case.get("court_code", ""), "case_number": case.get("case_number")}


def map_row(cfg: dict, row: dict) -> dict:
    """Одна строка источника → что будет отправлено (дело, наблюдения, документ, день календаря)."""
    maps = cfg.get("maps", {})
    out: dict = {}
    if "cases" in cfg:
        c = {k: render(cfg["cases"].get(k), row, maps) for k in CASE_KEYS if k in cfg["cases"]}
        c = {k: v for k, v in c.items() if v not in (None, "")}
        if "appeal_flag" in c:
            c["appeal_flag"] = c["appeal_flag"] == "true"
        if "aliases" in cfg["cases"]:
            al = render(cfg["cases"]["aliases"], row, maps) or ""
            c["aliases"] = [a.strip() for a in re.split(r"[;,\n]", al) if a.strip()]
        out["case"] = c
    if "observations" in cfg:
        o = cfg["observations"]
        ref = out.get("case") and _case_ref(out["case"])
        if not ref:
            ref = {k: render(o[k], row, maps) for k in ("uid", "court_code", "case_number", "case_id") if k in o}
            ref = {k: v for k, v in ref.items() if v}
        src = render(o.get("source", ""), row, maps)
        sref = render(o.get("source_ref", ""), row, maps) or ""
        obs = []
        for field, tpl in o.get("fields", {}).items():
            spec = tpl if isinstance(tpl, dict) else {"value": tpl}
            val = render(spec["value"], row, maps)
            if val in (None, "") and not o.get("send_empty", False):
                continue
            item = {**ref, "field": field, "source": src, "source_ref": sref, "value": val}
            for extra in ("quote", "page", "document_sha256"):
                if extra in spec:
                    item[extra] = render(spec[extra], row, maps)
            if "page" in item:
                item["page"] = int(item["page"]) if str(item["page"]).isdigit() else None
            obs.append(item)
        out["observations"] = obs
    if "documents" in cfg:
        d = cfg["documents"]
        doc = {k: render(d.get(k), row, maps) for k in DOC_KEYS if k in d}
        doc = {k: v for k, v in doc.items() if v not in (None, "")}
        if d.get("meta"):
            doc["meta"] = {k: render(v, row, maps) for k, v in d["meta"].items()}
        case_ref = out.get("case") and _case_ref(out["case"])
        if not case_ref and d.get("case"):
            case_ref = {k: render(v, row, maps) for k, v in d["case"].items()}
            case_ref = {k: v for k, v in case_ref.items() if v}
        if case_ref:
            doc["case"] = case_ref
        if d.get("file"):
            doc["_file"] = render(d["file"], row, maps)
        if d.get("signature_file"):
            doc["_signature"] = render(d["signature_file"], row, maps)
        out["document"] = doc
    if "calendar" in cfg:
        k = cfg["calendar"]
        day = render(k["date"], row, maps)
        kind = render(k.get("day_type", ""), row, maps)
        nonworking = (kind in k.get("nonworking_values", [])) if "day_type" in k else (render(k.get("working", "true"), row, maps) != "true")
        out["calendar_day"] = (day, nonworking)
    return out


def run_in(cfg: dict, base: Path, ld: Lawdesk | None, limit: int | None, dry: bool) -> int:
    cases, observations, documents, uploads, calendar = [], [], [], [], {}
    problems = 0
    for i, row in enumerate(read_rows(cfg["source"], base, limit), 1):
        try:
            m = map_row(cfg, row)
        except (KeyError, ValueError) as e:
            problems += 1
            msg = f"нет колонки {e}" if isinstance(e, KeyError) else str(e)
            log.warning("строка %d: %s — пропущена", i, msg)
            continue
        if dry and i <= 3:
            log.info("строка %d из источника: %s", i, json.dumps(row, ensure_ascii=False, default=str)[:600])
            log.info("   → будет отправлено: %s", json.dumps(m, ensure_ascii=False, default=str)[:900])
        if m.get("case"):
            if not (m["case"].get("uid") or m["case"].get("case_number")):
                problems += 1
                log.warning("строка %d: у дела нет ни УИД, ни номера — пропущена", i)
                continue
            cases.append(m["case"])
        observations += m.get("observations", [])
        if m.get("document"):
            doc = m["document"]
            (uploads if doc.get("_file") else documents).append(doc)
        if m.get("calendar_day"):
            day, nonworking = m["calendar_day"]
            if day:
                calendar.setdefault(day[:4], set())
                if nonworking:
                    calendar[day[:4]].add(day)
    log.info("прочитано: дел %d, значений полей %d, документов %d (с файлами %d), лет календаря %d; пропущено строк %d",
             len(cases), len(observations), len(documents) + len(uploads), len(uploads), len(calendar), problems)
    if dry or ld is None:
        return problems

    def report(kind: str, res: list[dict]):
        nonlocal problems
        bad = [r for r in res if not r.get("ok")]
        problems += len(bad)
        warns = [w for r in res if r.get("ok") for w in r.get("warnings", [])]
        log.info("%s: отправлено %d, ошибок %d, предупреждений %d", kind, len(res), len(bad), len(warns))
        for r in bad[:20]:
            log.warning("   ошибка: %s", r.get("error"))
        for w in warns[:20]:
            log.warning("   предупреждение: %s", w)

    if cases:
        report("дела", ld.cases(cases))
    if documents:
        report("документы", ld.documents(documents))
    for doc in uploads:
        f, sig = doc.pop("_file"), doc.pop("_signature", None)
        try:
            ld.upload(_resolve(base, f), doc, _resolve(base, sig) if sig else None)
        except (LawdeskError, OSError) as e:
            problems += 1
            log.warning("файл %s: %s", f, e)
    if uploads:
        log.info("файлы: загружено %d", len(uploads))
    if observations:
        report("значения полей", ld.observations(observations))
    for year, days in sorted(calendar.items()):
        try:
            r = ld.calendar(int(year), sorted(days), cfg["calendar"].get("source_name", cfg["connector"]["name"]))
            log.info("календарь %s: нерабочих дней %d, пересчитано сроков %d", year, r["nonworking"], r["deadlines_changed"])
        except LawdeskError as e:
            problems += 1
            log.warning("календарь %s: %s", year, e.detail)
    return problems


# =============================================================================================
# Направление «out»: лента изменений → файл / HTTP-сервис
# =============================================================================================

def event_row(ev: dict, case: dict | None, fields: dict) -> dict:
    """Плоская строка события для шаблонов колонок: {action}, {field}, {value}, {case.uid}, …"""
    data = ev.get("data") or {}
    after = data.get("after") or {}
    before = data.get("before") or {}
    field = data.get("field", "")
    return {
        **{k: v for k, v in ev.items() if k != "data"}, "data": data,
        "field": field, "field_label": fields.get(field, field),
        "value": after.get("value", "") if isinstance(after, dict) else after,
        "previous": before.get("value", "") if isinstance(before, dict) else before,
        "note": data.get("note", ""), "chosen": data.get("chosen", ""),
        "case": case or {}, "date": ev.get("ts", "")[:10],
    }


def run_out(cfg: dict, base: Path, ld: Lawdesk, limit: int | None, dry: bool) -> int:
    feed = cfg.get("feed", {})
    state = _resolve(base, feed.get("state_file", f"состояние/{_slug(cfg['connector']['name'])}.курсор"))
    cursor = int(state.read_text().strip() or 0) if state.exists() else int(feed.get("start_from", 0))
    actions = ",".join(feed.get("actions", ["value_resolved"]))
    fields = {f["key"]: f["label"] for f in ld.request("GET", "/api/v1/fields")}
    cases_cache: dict[int, dict] = {}
    rows, last = [], cursor
    while True:
        page = ld.changes(last, actions, limit=500)
        for ev in page["items"]:
            cid = ev.get("case_id")
            if cid and cid not in cases_cache:
                try:
                    cases_cache[cid] = ld.get_case(cid)
                except LawdeskError:
                    cases_cache[cid] = {}
            r = event_row(ev, cases_cache.get(cid), fields)
            cols = cfg["sink"].get("columns")
            rows.append({k: render(v, r, cfg.get("maps", {}), strict=False) for k, v in cols.items()} if cols else r)
        if page["next_cursor"] == last or (limit and len(rows) >= limit):
            last = page["next_cursor"]
            break
        last = page["next_cursor"]
    log.info("новых событий: %d (курсор %d → %d)", len(rows), cursor, last)
    if dry:
        for r in rows[:3]:
            log.info("   будет записано: %s", json.dumps(r, ensure_ascii=False, default=str)[:600])
        return 0
    if rows:
        write_sink(cfg["sink"], base, rows, cfg["connector"]["name"])
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(str(last))  # курсор сохраняется только после успешной записи
    return 0


def write_sink(sink: dict, base: Path, rows: list[dict], name: str) -> None:
    t = sink.get("type")
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if t in ("csv", "json"):
        path = _resolve(base, sink["path"].replace("{date}", stamp))
        path.parent.mkdir(parents=True, exist_ok=True)
        if t == "csv":
            new = not path.exists() or sink.get("mode", "new") == "new"
            with open(path, "a" if not new else "w", encoding=sink.get("encoding", "utf-8-sig"), newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=sink.get("delimiter", ";"), extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerows({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in r.items()} for r in rows)
        else:
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        log.info("записано в %s: %d строк", path, len(rows))
    elif t == "http":
        batch = int(sink.get("batch", 200))
        for i in range(0, len(rows), batch):
            body = {"source": "lawdesk", "connector": name, "items": rows[i:i + batch]} if sink.get("envelope", True) else rows[i:i + batch]
            _http_json(sink["url"], sink, sink.get("method", "POST"), body)
        log.info("отправлено в %s: %d строк", sink["url"], len(rows))
    else:
        raise ConfigError(f"[sink] type = «{t}» — неизвестный приёмник. Доступны: csv, json, http")


# =============================================================================================
# Проверка настроек, запуск, шаблоны
# =============================================================================================

ALLOWED = {
    "connector": {"name", "api_url", "api_key_env", "api_key_file", "direction", "cafile", "log_dir", "limit"},
    "source": {"type", "path", "encoding", "delimiter", "sheet", "skip_rows", "date_columns", "items_path", "pattern",
               "recursive", "url", "user", "password", "password_env", "headers", "params", "timeout", "page_size",
               "next_path", "offset_param", "limit_param", "entity", "select", "filter", "expand", "orderby", "query",
               "url_env", "only_if"},
    "cases": set(CASE_KEYS) | {"aliases"},
    "observations": {"source", "source_ref", "fields", "send_empty", "uid", "court_code", "case_number", "case_id"},
    "documents": set(DOC_KEYS) | {"file", "signature_file", "meta", "case"},
    "calendar": {"date", "day_type", "nonworking_values", "working", "source_name"},
    "feed": {"actions", "state_file", "start_from"},
    "sink": {"type", "path", "encoding", "delimiter", "mode", "url", "method", "user", "password", "password_env",
             "headers", "timeout", "batch", "envelope", "columns"},
    "maps": None,
}


def load_config(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"нет файла настроек {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"ошибка в записи файла настроек: {e}. Частые причины: нет кавычек вокруг текста; "
                          f"русское имя слева от «=» или в [квадратных скобках] без кавычек (пишите \"Колонка\" = … "
                          f"или латиницей); обратная косая черта в пути Windows (пишите / или удвойте \\\\)") from None
    for section, val in cfg.items():
        if section not in ALLOWED:
            raise ConfigError(f"неизвестный раздел [{section}]. Возможные: {', '.join('[' + s + ']' for s in ALLOWED)}")
        if ALLOWED[section] is None or not isinstance(val, dict):
            continue
        for k in val:
            if k not in ALLOWED[section] and not (section == "observations" and k == "fields"):
                hint = min(ALLOWED[section], key=lambda a: _distance(a, k))
                raise ConfigError(f"[{section}] неизвестный параметр «{k}». Может быть, «{hint}»?")
    con = cfg.get("connector", {})
    if not con.get("name"):
        raise ConfigError("в разделе [connector] укажите name — название подключения (для журнала)")
    direction = con.get("direction", "in")
    if direction not in ("in", "out"):
        raise ConfigError("[connector] direction: in (в рабочее место) или out (наружу)")
    if direction == "in" and "source" not in cfg:
        raise ConfigError("для direction = \"in\" нужен раздел [source] — откуда брать данные")
    if direction == "in" and not any(k in cfg for k in ("cases", "observations", "documents", "calendar")):
        raise ConfigError("укажите, что делать с данными: раздел [cases], [observations], [documents] или [calendar]")
    if direction == "out" and "sink" not in cfg:
        raise ConfigError("для direction = \"out\" нужен раздел [sink] — куда записывать")
    return cfg


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _slug(s: str) -> str:
    return re.sub(r"[^\w\-]+", "_", s).strip("_")[:60] or "коннектор"


def client(cfg: dict, base: Path) -> Lawdesk:
    con = cfg["connector"]
    url = con.get("api_url") or os.environ.get("LAWDESK_URL")
    key = None
    if con.get("api_key_file"):
        key = _resolve(base, con["api_key_file"]).read_text(encoding="utf-8").strip()
    key = key or os.environ.get(con.get("api_key_env", "LAWDESK_KEY"))
    if not url:
        raise ConfigError("не указан адрес рабочего места: [connector] api_url или переменная LAWDESK_URL")
    if not key:
        raise ConfigError(f"нет API-ключа: переменная окружения {con.get('api_key_env', 'LAWDESK_KEY')} или файл [connector] api_key_file")
    return Lawdesk(url, key, cafile=con.get("cafile"))


def check_templates(cfg: dict, base: Path) -> None:
    """Все ли колонки из шаблонов есть в источнике (по первым строкам)."""
    if "source" not in cfg:
        return
    rows = list(read_rows(cfg["source"], base, limit=20))
    if not rows:
        log.warning("источник вернул 0 строк — проверьте путь, запрос или фильтр only_if")
        return
    log.info("колонки источника: %s", ", ".join(map(str, rows[0].keys())))
    used = []
    for section in ("cases", "observations", "documents", "calendar"):
        s = cfg.get(section, {})
        for k, v in s.items():
            if k == "fields":
                for fv in v.values():
                    used += template_columns(fv["value"] if isinstance(fv, dict) else fv)
            elif isinstance(v, str):
                used += template_columns(v)
    missing = sorted({c for c in used if all(_missing(r, c) for r in rows)})
    if missing:
        raise ConfigError("в источнике нет колонок: " + ", ".join(f"«{c}»" for c in missing))
    log.info("все колонки из шаблонов найдены (%d)", len(set(used)))


def _missing(row: dict, col: str) -> bool:
    try:
        lookup(row, col)
        return False
    except KeyError:
        return True


def check_fields(cfg: dict, ld: Lawdesk | None) -> None:
    obs = cfg.get("observations", {}).get("fields", {})
    if not obs or ld is None:
        return
    try:
        known = {f["key"] for f in ld.request("GET", "/api/v1/fields")}
    except Exception as e:  # noqa: BLE001
        log.warning("не удалось получить список полей с сервера (%s) — пропускаю проверку полей", e)
        return
    unknown = [k for k in obs if k not in known]
    if unknown:
        log.warning("поля %s неизвестны рабочему месту — будут приняты как текстовые. Если это опечатка, "
                    "сверьтесь со списком: python lawdesk_connect.py поля %s", ", ".join(unknown), "<настройки>")


def setup_logging(cfg: dict | None, base: Path) -> None:
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h)
    if cfg:
        d = _resolve(base, cfg["connector"].get("log_dir", "журналы"))
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(d / f"{_slug(cfg['connector']['name'])}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)


COMMANDS = {"проверить": "check", "check": "check", "запустить": "run", "run": "run",
            "шаблон": "template", "template": "template", "поля": "fields", "fields": "fields"}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help", "помощь"):
        print(__doc__)
        return 0
    cmd = COMMANDS.get(argv[1])
    if cmd is None:
        print(f"Неизвестная команда «{argv[1]}». Команды: проверить, запустить, шаблон, поля.")
        return 2
    if cmd == "template":
        kind = argv[2] if len(argv) > 2 else ""
        tpl = Path(__file__).parent / "примеры" / f"{kind}.toml"
        if not kind or not tpl.exists():
            names = sorted(p.stem for p in (Path(__file__).parent / "примеры").glob("*.toml"))
            print("Укажите шаблон: " + ", ".join(names))
            return 2
        sys.stdout.write(tpl.read_text(encoding="utf-8"))
        return 0
    if len(argv) < 3:
        print("Укажите файл настроек, например: python lawdesk_connect.py проверить примеры/csv.toml")
        return 2
    path = Path(argv[2]).resolve()
    base = path.parent
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    try:
        cfg = load_config(path)
        setup_logging(cfg, base)
        con = cfg["connector"]
        limit = limit or con.get("limit")
        log.info("=== %s · %s · %s · lawdesk_connect %s ===", con["name"],
                 "проверка" if cmd == "check" else "запуск", dt.datetime.now().strftime("%d.%m.%Y %H:%M"), VERSION)
        if cmd == "fields":
            for f in client(cfg, base).request("GET", "/api/v1/fields"):
                print(f"{f['key']:<24} {f['label']:<34} {f['kind']:<6} {f['group']}")
            return 0
        direction = con.get("direction", "in")
        if direction == "in":
            check_templates(cfg, base)
            ld = None
            if cmd == "run" or con.get("api_url") or os.environ.get("LAWDESK_URL"):
                try:
                    ld = client(cfg, base)
                except ConfigError as e:
                    if cmd == "run":
                        raise
                    log.info("(связь с рабочим местом не проверялась: %s)", e)
            check_fields(cfg, ld)
            problems = run_in(cfg, base, ld if cmd == "run" else None, limit, dry=(cmd == "check"))
        else:
            ld = client(cfg, base)
            problems = run_out(cfg, base, ld, limit, dry=(cmd == "check"))
        log.info("готово%s", f", проблем: {problems} (подробности выше и в журнале)" if problems else ", без ошибок")
        return 1 if problems else 0
    except ConfigError as e:
        if not log.handlers:
            setup_logging(None, base)
        log.error("ОШИБКА НАСТРОЕК: %s", e)
        return 2
    except LinkError as e:
        log.error("ОШИБКА СВЯЗИ С ВНЕШНЕЙ СИСТЕМОЙ: %s", e)
        log.error("→ ничего не потеряно: при следующем запуске всё будет повторено")
        return 3
    except LawdeskError as e:
        log.error("ОШИБКА РАБОЧЕГО МЕСТА (HTTP %s): %s", e.status, e.detail)
        if e.status == 401:
            log.error("→ проверьте API-ключ: он мог быть отозван или скопирован не полностью")
        if e.status == 403:
            log.error("→ у ключа нет нужной области доступа (read / ingest / export / calendar) — см. «Сервисы и API»")
        return 3
    except (OSError, urllib.error.URLError) as e:
        log.error("ОШИБКА ДОСТУПА: %s", e)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
