"""Калькулятор неустойки 214-ФЗ: произвольный расчёт и расчёт по делу (с подстановкой цены договора и срока)."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..fields import parse_date, parse_money
from ..penalty import PenaltyConfigError, calculate, load_rules
from ..security import Principal, require
from .cases import DISPUTED, load_case

router = APIRouter(prefix="/api/v1", tags=["Калькулятор неустойки"])


class CalcIn(BaseModel):
    price: Decimal = Field(gt=0, description="Цена договора, ₽")
    due_date: date = Field(description="Последний день срока передачи по договору")
    end_date: date | None = Field(None, description="Дата фактической передачи; пусто — сегодня")
    citizen: bool = True
    claim_deadline: date | None = Field(None, description="Когда истёк срок добровольного удовлетворения претензии (для штрафа)")


def _run(body: CalcIn) -> dict:
    try:
        r = calculate(body.price, body.due_date, body.end_date or clock.today(), body.citizen, body.claim_deadline)
    except PenaltyConfigError as e:
        raise HTTPException(503, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {
        "price": float(r.price), "due_date": r.due_date, "end_date": r.end_date, "base_rate": float(r.base_rate),
        "citizen": r.citizen, "days_total": r.days_total, "days_counted": r.days_counted, "total": float(r.total),
        "fine_percent": r.fine_percent, "fine": float(r.fine) if r.fine is not None else None, "fine_note": r.fine_note,
        "formula": r.formula, "rules_file": load_rules().source,
        "segments": [{"start": s.start, "end": s.end, "days": s.days, "rate": float(s.rate), "excluded": s.excluded,
                      "note": s.note, "amount": float(s.amount)} for s in r.segments],
    }


@router.post("/penalty/calc")
def calc(body: CalcIn, _: Principal = Depends(require(role="viewer", scope="read"))):
    return _run(body)


@router.get("/cases/{case_id}/penalty")
def case_defaults(case_id: int, db: Session = Depends(get_db), _: Principal = Depends(require(role="viewer", scope="read"))):
    """Что известно по делу для расчёта: цена договора, срок передачи, присуждённая неустойка (для сравнения)."""
    c = load_case(db, case_id)
    v = {x.field: x.value for x in c.values if x.status not in DISPUTED and x.value}
    price = parse_money(v.get("contract_price", "")) if v.get("contract_price") else None
    due = parse_date(v.get("transfer_due", "")) if v.get("transfer_due") else None
    awarded = parse_money(v.get("amount_penalty", "")) if v.get("amount_penalty") else None
    out = {"price": float(price) if price else None, "due_date": due, "awarded_penalty": float(awarded) if awarded else None,
           "result": None}
    if price and due and due < clock.today():
        out["result"] = _run(CalcIn(price=price, due_date=due))
    return out
