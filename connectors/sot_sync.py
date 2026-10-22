"""Синхронизация sot.db → рабочее место юриста (через API, как любой другой сервис).

sot.db открывается ТОЛЬКО НА ЧТЕНИЕ. Отправка идемпотентна: повторный запуск после пересборки
sot.db обновит значения, не создавая дублей (дело — по УИД / коду суда + номеру; наблюдение —
по источнику + ключу записи).

Схема sot.db меняется вместе с конвейером, поэтому сопоставление вынесено в MAPPING ниже.
Перед первым запуском:
    python sot_sync.py --db ../sot/sot.db --schema          # посмотреть таблицы и колонки
    python sot_sync.py --db ../sot/sot.db --dry-run         # проверить сопоставление, ничего не отправляя
    LAWDESK_KEY=ldk_... python sot_sync.py --db ../sot/sot.db --url https://lawdesk.local

Сервису нужен ключ с областями ingest (и read для --dry-run не нужен).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lawdesk_client import Lawdesk  # noqa: E402

# --------------------------------------------------------------------------------------------
# Сопоставление. Имена колонок — по описанию sot.db (журнал работ 12–16.10.2026); если в твоей
# базе колонка называется иначе — поправь здесь. Список вариантов: берётся первая существующая.
# --------------------------------------------------------------------------------------------
MAPPING = {
    "cases": {
        "table": "cases",
        "id": ["case_id", "id"],
        "court_code": ["court_code", "court", "court_key"],
        "court_name": ["court_name", "court_title"],
        "case_number": ["case_key", "case_number", "number"],
        "uid": ["case_uid", "uid"],
        "legal_entity": ["entity", "legal_entity", "yurlico"],
        "complex": ["complex", "zhk"],
        "building": ["building", "korpus"],
        "flat": ["flat", "kv"],
        "contract_no": ["contract_no", "contract"],
        "plaintiffs": ["plaintiffs", "istcy"],
        "subject": ["subject", "predmet"],
        "status": ["status", "state"],
        "outcome": ["outcome", "ishod"],
        "appeal_flag": ["appeal_possible", "appeal_flag"],
    },
    # Псевдонимы номеров: case_aliases(case_id, court, case_key)
    "aliases": {"table": "case_aliases", "case_id": ["case_id"], "number": ["case_key", "number"]},
    # УИД дела, если он в отдельной таблице
    "uids": {"table": "case_uid", "case_id": ["case_id"], "uid": ["uid", "case_uid"]},
    # Значения полей. Две поддерживаемые формы:
    #  a) колонка с JSON {источник: значение}  — "sources_json"
    #  b) колонки на каждый источник           — "source_columns"
    "values": {
        "table": "case_values",
        "case_id": ["case_id"],
        "field": ["field", "name", "key"],
        "sources_json": ["sources", "values_by_source", "by_source", "src_values"],
        "source_columns": {"1С": ["v_1c", "val_1c", "src_1c"], "отчёт": ["v_report", "val_otchet", "src_otchet"],
                           "OCR": ["v_ocr", "val_ocr", "src_ocr"], "письмо": ["v_letter", "val_digital", "src_letter"]},
    },
}

# Поля sot.db → ключи полей рабочего места (см. GET /api/v1/fields). Неизвестные отправляются как есть.
FIELD_MAP = {
    "суд": "court", "court": "court",
    "судья": "judge", "judge": "judge",
    "истцы": "plaintiffs", "plaintiffs": "plaintiffs",
    "дата решения": "decision_date", "decision_date": "decision_date",
    "исход": "outcome", "outcome": "outcome",
    "корпус": "building", "building": "building",
    "квартира": "flat", "flat": "flat",
    "договор": "contract_no", "contract_no": "contract_no",
    "долг": "amount_debt", "основной долг": "amount_debt", "debt": "amount_debt",
    "неустойка": "amount_penalty", "penalty": "amount_penalty",
    "штраф": "amount_fine", "fine": "amount_fine",
    "кмв": "amount_moral", "моральный вред": "amount_moral", "moral": "amount_moral",
    "экспертиза": "amount_expertise", "почтовые": "amount_postal", "представитель": "amount_representative",
    "госпошлина": "amount_duty", "заявлено": "claim_total", "claim": "claim_total", "claim_kop": "claim_total",
}
SOURCE_MAP = {"1c": "1С", "1с": "1С", "vigr": "1С", "vi2": "1С", "r2": "1С", "uid": "1С", "otchet": "отчёт",
              "report": "отчёт", "отчет": "отчёт", "ocr": "OCR", "letter": "письмо", "digital": "письмо", "цифра": "письмо"}
KOPECK_FIELDS = {"claim_kop"}  # значения в копейках → рубли


def connect_ro(path: str) -> sqlite3.Connection:
    p = Path(path).resolve()
    if not p.exists():
        raise SystemExit(f"Нет файла {p}")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def columns(con, table: str) -> list[str]:
    return [r["name"] for r in con.execute(f'PRAGMA table_info("{table}")')]


def pick(cols: list[str], variants) -> str | None:
    if isinstance(variants, str):
        variants = [variants]
    return next((v for v in variants if v in cols), None)


def print_schema(con) -> None:
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        print(f"{t} ({n}): {', '.join(columns(con, t))}")


def resolve_mapping(con) -> dict:
    """Проверить сопоставление на реальной базе; вернуть фактические имена колонок."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out, problems = {}, []
    for part, spec in MAPPING.items():
        t = spec["table"]
        if t not in tables:
            problems.append(f"[{part}] нет таблицы {t}")
            continue
        cols = columns(con, t)
        m = {"table": t}
        for k, v in spec.items():
            if k == "table":
                continue
            if k == "source_columns":
                m[k] = {src: c for src, vs in v.items() if (c := pick(cols, vs))}
            else:
                m[k] = pick(cols, v)
        out[part] = m
    c = out.get("cases", {})
    if c and not c.get("id"):
        problems.append("[cases] не найдена колонка идентификатора дела")
    if c and not (c.get("uid") or c.get("case_number")):
        problems.append("[cases] нет ни УИД, ни номера дела")
    v = out.get("values", {})
    if v and not (v.get("sources_json") or v.get("source_columns")):
        problems.append("[values] не найдены значения по источникам (ни JSON-колонки, ни колонок источников)")
    return {"map": out, "problems": problems}


def norm_source(s: str) -> str:
    k = str(s).strip()
    return SOURCE_MAP.get(k.casefold(), k)


def read_cases(con, m: dict):
    c, al, ui = m.get("cases"), m.get("aliases"), m.get("uids")
    aliases: dict = {}
    if al and al.get("case_id") and al.get("number"):
        for r in con.execute(f'SELECT "{al["case_id"]}" cid, "{al["number"]}" n FROM "{al["table"]}"'):
            aliases.setdefault(r["cid"], []).append(r["n"])
    uids: dict = {}
    if ui and ui.get("case_id") and ui.get("uid"):
        for r in con.execute(f'SELECT "{ui["case_id"]}" cid, "{ui["uid"]}" u FROM "{ui["table"]}"'):
            uids.setdefault(r["cid"], r["u"])
    keys = [k for k in c if k not in ("table",) and c[k]]
    sel = ", ".join(f'"{c[k]}" AS "{k}"' for k in keys)
    for r in con.execute(f'SELECT {sel} FROM "{c["table"]}"'):
        d = dict(r)
        sid = d.pop("id")
        item = {k: (str(v) if v is not None and k != "appeal_flag" else v) for k, v in d.items() if v not in (None, "")}
        if "appeal_flag" in item:
            item["appeal_flag"] = bool(item["appeal_flag"])
        item["uid"] = item.get("uid") or uids.get(sid)
        item["aliases"] = [a for a in aliases.get(sid, []) if a != item.get("case_number")]
        item["extra"] = {"sot_case_id": sid}
        if not item["uid"]:
            item.pop("uid")
        yield sid, item


def read_values(con, m: dict, case_keys: dict):
    v = m.get("values")
    if not v:
        return
    sel = [f'"{v["case_id"]}" AS cid', f'"{v["field"]}" AS field']
    if v.get("sources_json"):
        sel.append(f'"{v["sources_json"]}" AS sj')
    for src, col in (v.get("source_columns") or {}).items():
        sel.append(f'"{col}" AS "src:{src}"')
    for r in con.execute(f'SELECT {", ".join(sel)} FROM "{v["table"]}"'):
        ref = case_keys.get(r["cid"])
        if ref is None:
            continue
        raw_field = str(r["field"])
        field = FIELD_MAP.get(raw_field.casefold(), raw_field)
        pairs: list[tuple[str, object]] = []
        if "sj" in r.keys() and r["sj"]:
            try:
                data = json.loads(r["sj"])
            except ValueError:
                data = {}
            if isinstance(data, dict):
                pairs += [(norm_source(k), val) for k, val in data.items()]
        for k in r.keys():
            if k.startswith("src:") and r[k] not in (None, ""):
                pairs.append((k[4:], r[k]))
        for src, val in pairs:
            if isinstance(val, dict):  # {"value": …, "ref": …, "quote": …}
                val, sref, quote = val.get("value"), val.get("ref"), val.get("quote")
            else:
                sref, quote = None, None
            if val in (None, ""):
                continue
            if isinstance(val, list):
                val = "; ".join(map(str, val))
            if raw_field in KOPECK_FIELDS:
                val = str((Decimal(str(val).replace(",", ".")) / 100).quantize(Decimal("0.01")))  # «12345» и «12345.0»
            yield {**ref, "field": field, "source": src, "source_ref": sref or "sot.db", "value": str(val), "quote": quote}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="Путь к sot.db")
    ap.add_argument("--url", default=os.environ.get("LAWDESK_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--key", default=os.environ.get("LAWDESK_KEY"))
    ap.add_argument("--schema", action="store_true", help="Показать схему sot.db и выйти")
    ap.add_argument("--dry-run", action="store_true", help="Проверить сопоставление и посчитать, ничего не отправляя")
    ap.add_argument("--limit", type=int, default=0, help="Только первые N дел (для пробы)")
    a = ap.parse_args()

    con = connect_ro(a.db)
    if a.schema:
        print_schema(con)
        return 0
    r = resolve_mapping(con)
    print("Сопоставление:", json.dumps(r["map"], ensure_ascii=False, indent=1))
    for p in r["problems"]:
        print("ВНИМАНИЕ:", p)
    if "cases" not in r["map"]:
        raise SystemExit("Нет таблицы дел — поправь MAPPING")

    cases = list(read_cases(con, r["map"]))
    if a.limit:
        cases = cases[: a.limit]
    case_keys = {sid: ({"uid": it["uid"]} if it.get("uid") else
                       {"court_code": it.get("court_code", ""), "case_number": it.get("case_number")}) for sid, it in cases}
    values = list(read_values(con, r["map"], case_keys))
    print(f"Дел: {len(cases)}, наблюдений: {len(values)}")
    print("По источникам:", dict(Counter(v["source"] for v in values)))
    print("По полям:", dict(Counter(v["field"] for v in values).most_common(30)))
    if a.dry_run:
        print("Пример дела:", json.dumps(cases[0][1] if cases else None, ensure_ascii=False))
        print("Пример наблюдения:", json.dumps(values[0] if values else None, ensure_ascii=False))
        return 0
    if not a.key:
        raise SystemExit("Нужен API-ключ: --key или LAWDESK_KEY")

    ld = Lawdesk(a.url, a.key)
    res = ld.cases(it for _, it in cases)
    bad = bad_cases = [x for x in res if not x["ok"]]
    warn = [w for x in res if x["ok"] for w in x.get("warnings", [])]
    print(f"Дела: отправлено {len(res)}, создано {sum(x.get('created', False) for x in res if x['ok'])}, ошибок {len(bad)}, предупреждений {len(warn)}")
    for x in bad[:20]:
        print("  ошибка:", x)
    for w in warn[:20]:
        print("  предупреждение:", w)
    res = ld.observations(values)
    bad = [x for x in res if not x["ok"]]
    print(f"Наблюдения: отправлено {len(res)}, ошибок {len(bad)}; статусы: {dict(Counter(x['status'] for x in res if x['ok']))}")
    for x in bad[:20]:
        print("  ошибка:", x)
    return 1 if bad or bad_cases else 0


if __name__ == "__main__":
    sys.exit(main())
