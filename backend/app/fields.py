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


FIELDS: dict[str, FieldDef] = {
    f.key: f
    for f in [
        FieldDef("court", "Суд", "text", "Дело"),
        FieldDef("judge", "Судья", "text", "Дело"),
        FieldDef("plaintiffs", "Истцы", "list", "Стороны"),
        FieldDef("defendant", "Ответчик (юрлицо)", "text", "Стороны"),
        FieldDef("decision_date", "Дата решения", "date", "Дело"),
        FieldDef("motivated_date", "Дата мотивированного решения", "date", "Дело"),
        FieldDef("effective_date", "Дата вступления в силу", "date", "Дело"),
        FieldDef("outcome", "Исход", "text", "Дело"),
        FieldDef("subject", "Предмет иска", "text", "Дело"),
        FieldDef("complex", "ЖК", "text", "Объект"),
        FieldDef("building", "Корпус", "text", "Объект"),
        FieldDef("flat", "Квартира", "text", "Объект"),
        FieldDef("contract_no", "Номер договора", "text", "Объект"),
        FieldDef("claim_total", "Заявлено всего", "money", "Суммы"),
        FieldDef("amount_debt", "Основной долг", "money", "Суммы"),
        FieldDef("amount_penalty", "Неустойка", "money", "Суммы"),
        FieldDef("amount_fine", "Штраф", "money", "Суммы"),
        FieldDef("amount_moral", "Компенсация морального вреда", "money", "Суммы"),
        FieldDef("amount_expertise", "Расходы на экспертизу", "money", "Суммы"),
        FieldDef("amount_postal", "Почтовые расходы", "money", "Суммы"),
        FieldDef("amount_representative", "Расходы на представителя", "money", "Суммы"),
        FieldDef("amount_duty", "Госпошлина", "money", "Суммы"),
    ]
}


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
