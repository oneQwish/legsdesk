"""Справочник полей дела, которые сверяются по источникам.

Ключ поля — латиницей (стабилен в API), подпись — для интерфейса. Неизвестные поля принимаются
как текстовые: сервис может прислать новое поле без правки кода.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: str  # text | money | date | list
    group: str


def _load_fields() -> dict[str, FieldDef]:
    """Справочник полей — из fields.toml (рядом с папкой app или по пути LAWDESK_FIELDS_FILE).
    Новое поле добавляется правкой файла и перезапуском сервера, программировать не нужно."""
    import os
    import tomllib
    from pathlib import Path

    path = Path(os.environ.get("LAWDESK_FIELDS_FILE", Path(__file__).resolve().parents[1] / "fields.toml"))
    with open(path, "rb") as f:
        data = tomllib.load(f)
    out: dict[str, FieldDef] = {}
    for key, spec in data.get("field", {}).items():
        kind = spec.get("kind", "text")
        if kind not in ("text", "money", "date", "list"):
            raise ValueError(f"fields.toml: у поля {key} тип «{kind}»; допустимо text, money, date, list")
        out[key] = FieldDef(key, spec.get("label", key), kind, spec.get("group", "Прочее"))
    return out


FIELDS: dict[str, FieldDef] = _load_fields()


def field_def(key: str) -> FieldDef:
    return FIELDS.get(key) or FieldDef(key, key, "text", "Прочее")


def parse_money(value: str) -> Decimal | None:
    s = re.sub(r"[\s ]", "", str(value)).replace(",", ".")
    s = re.sub(r"(руб\.?|₽)$", "", s, flags=re.I)
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: str) -> date | None:
    s = str(value).strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s) or None
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    return None


def normalize(key: str, value: str | None) -> str:
    """Приведённый вид значения для сравнения источников между собой."""
    if value is None:
        return ""
    kind = field_def(key).kind
    if kind == "money":
        d = parse_money(value)
        return str(d) if d is not None else str(value).strip()
    if kind == "date":
        d = parse_date(value)
        return d.isoformat() if d else str(value).strip()
    s = str(value).casefold().replace("ё", "е")
    s = re.sub(r"[\"«»“”'`]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if kind == "list":
        parts = sorted(p.strip() for p in re.split(r"[;\n]", s) if p.strip())
        return "; ".join(parts)
    return s
