"""Данные для пилота: сотни вымышленных дел со всеми ситуациями, которые нужно проверить руками.

Даты считаются от сегодняшнего дня, поэтому в любой день запуска есть просроченные сроки, сроки на
сегодня, на неделю и дальше. Люди, номера и суммы — вымышленные (персональных данных нет).

    LAWDESK_KEY=ldk_... python pilot_seed.py --url http://127.0.0.1:8000 [--cases 300] [--force]

Что появляется (сценарии — в docs/пилот.md):
  - дела трёх юрлиц с расхождениями источников (1С, отчёт, OCR, письмо) → очередь конфликтов;
  - «заявлено» по 1С → полоса «присуждено от заявленного»;
  - ответственные: ivanova и sidorova (юристы), часть дел без ответственного;
  - акты: решения (апелляция и вступление в силу), апелляционные определения (кассация),
    определения (частная жалоба), заочные решения (отмена заочного);
  - документы без дела — для ручной привязки; дела-дубли — для слияния; дела без УИД;
  - производственный календарь текущего и следующего года;
  - несколько задач в очереди.
"""
from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from demo_seed import COURTS, make_sot, tiny_pdf  # noqa: E402
from lawdesk_client import Lawdesk  # noqa: E402

LAWYERS = ["ivanova", "sidorova"]
HOLIDAYS = {(1, d) for d in range(1, 9)} | {(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)}


def nonworking_days(year: int) -> list[str]:
    """Выходные и праздники (ст. 112 ТК) — без переносов; для пилота этого достаточно."""
    d, out = date(year, 1, 1), []
    while d.year == year:
        if d.weekday() >= 5 or (d.month, d.day) in HOLIDAYS:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def upload(ld: Lawdesk, name: str, title: str, meta: dict) -> dict:
    p = Path(tempfile.mkdtemp()) / name
    p.write_bytes(tiny_pdf(title))
    return ld.upload(p, meta)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("LAWDESK_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--key", default=os.environ.get("LAWDESK_KEY"))
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--force", action="store_true", help="загрузить, даже если дела уже есть")
    a = ap.parse_args()
    if not a.key:
        print("Нужен ключ: --key или LAWDESK_KEY (области read, ingest, tasks, calendar)")
        return 2

    ld = Lawdesk(a.url, a.key)
    if ld.find_cases("", size=1)["total"] and not a.force:
        print("В базе уже есть дела — пилотные данные не загружаю (повторно: --force).")
        return 0

    today = date.today()
    rng = random.Random(2027)

    print("Календарь…")
    for y in (today.year, today.year + 1):
        ld.calendar(y, nonworking_days(y), "пилот (ст. 112 ТК)")

    print(f"Дела и значения источников ({a.cases})…")
    sot = Path(tempfile.mkdtemp()) / "pilot_sot.db"
    make_sot(sot, a.cases, seed=2027)
    subprocess.run([sys.executable, str(Path(__file__).parent / "sot_sync.py"), "--db", str(sot),
                    "--url", a.url, "--key", a.key], check=True, stdout=subprocess.DEVNULL)

    cases = []
    page = 1
    while True:
        r = ld.request("GET", "/api/v1/cases", params={"size": 500, "page": page, "sort": "id"})
        cases += r["items"]
        if len(cases) >= r["total"]:
            break
        page += 1

    print("Ответственные и «заявлено»…")
    upd, obs = [], []
    for c in cases:
        resp = rng.choice(LAWYERS + LAWYERS + [""])  # треть дел — без ответственного
        upd.append({"uid": c["uid"], "court_code": c["court_code"], "case_number": c["case_number"], "responsible": resp})
        if c.get("awarded") and rng.random() < .85:
            claimed = round(c["awarded"] * rng.uniform(1.2, 2.6), 2)
            obs.append({"case_id": c["id"], "field": "claim_total", "source": "1С", "value": f"{claimed:.2f}"})
    ld.cases([{k: v for k, v in u.items() if v is not None} for u in upd])
    ld.observations(obs)

    print("Акты и сроки…")
    n_docs = 0
    for c in cases:
        ref = {"case_id": c["id"]}
        roll = rng.random()
        if roll < .45:  # решение: срок апелляции — месяц от мотивированного; разброс даёт просрочки и «сегодня»
            dec = today - timedelta(days=rng.randint(0, 36))  # несколько апелляций просрочено — остальные впереди
            motivated = dec + timedelta(days=rng.randint(0, 7))
            if motivated > today:
                motivated = today
            meta = {"kind": rng.choice(["письмо", "скан"]), "act_type": "решение", "instance": "первая",
                    "act_date": dec.isoformat(), "case": ref, "text_source": "цифровой",
                    "motivated_date": motivated.isoformat() if rng.random() < .85 else None,
                    "text": f"РЕШЕНИЕ\nИменем Российской Федерации\n{c['court_name']}\nДело № {c['case_number']}\n"
                            f"Истцы: {c['plaintiffs']}\nРЕШИЛ: иск удовлетворить частично.\n(вымышленный текст для пилота)"}
            if meta["kind"] == "письмо":
                meta["track_no"] = f"8021{rng.randint(10**9, 10**10 - 1)}"
            upload(ld, f"{c['id']}_решение.pdf", f"Reshenie {c['case_number']}", meta)
        elif roll < .60:  # апелляционное определение → кассация (3 месяца)
            d = today - timedelta(days=rng.randint(10, 100))
            upload(ld, f"{c['id']}_апелляция.pdf", f"Apell. opredelenie {c['case_number']}",
                   {"kind": "письмо", "act_type": "апелляционное определение", "instance": "апелляция",
                    "act_date": d.isoformat(), "case": ref, "text": "АПЕЛЛЯЦИОННОЕ ОПРЕДЕЛЕНИЕ (вымышленный текст)",
                    "text_source": "цифровой"})
        elif roll < .70:  # определение о расходах → частная жалоба (15 рабочих дней)
            d = today - timedelta(days=rng.randint(0, 25))
            upload(ld, f"{c['id']}_определение.pdf", f"Opredelenie {c['case_number']}",
                   {"kind": "письмо", "act_type": "определение о судебных расходах", "instance": "первая",
                    "act_date": d.isoformat(), "case": ref, "text": "ОПРЕДЕЛЕНИЕ о судебных расходах (вымышленный текст)",
                    "text_source": "цифровой"})
        elif roll < .74:  # заочное решение → отмена заочного (7 рабочих дней от вручения)
            d = today - timedelta(days=rng.randint(10, 40))
            delivered = today - timedelta(days=rng.randint(0, 8))
            upload(ld, f"{c['id']}_заочное.pdf", f"Zaochnoe {c['case_number']}",
                   {"kind": "скан", "act_type": "заочное решение", "instance": "первая", "act_date": d.isoformat(),
                    "case": ref, "meta": {"delivered_date": delivered.isoformat()},
                    "text": "ЗАОЧНОЕ РЕШЕНИЕ (вымышленный текст)", "text_source": "OCR"})
        else:
            continue
        n_docs += 1

    print("Документы без дела и дубли…")
    for i in range(8):  # ссылка на номер, которого нет в реестре → «не привязан», привязать вручную
        upload(ld, f"письмо_{i}.pdf", f"Pismo {i}",
               {"kind": "письмо", "act_type": rng.choice(["решение", "определение о судебных расходах"]),
                "instance": "первая", "act_date": (today - timedelta(days=rng.randint(1, 20))).isoformat(),
                "track_no": f"8021{rng.randint(10**9, 10**10 - 1)}",
                "case": {"court_code": COURTS[0][0], "case_number": f"2-{9000 + i}/25"},
                "text": "Письмо суда: номер дела в письме не найден в реестре (вымышленный текст)", "text_source": "цифровой"})
    dups = rng.sample([c for c in cases if c["uid"]], k=min(4, len(cases)))
    for c in dups:  # то же дело под номером материала, без УИД: найти по истцу/квартире и слить
        ld.cases([{"court_code": c["court_code"], "case_number": f"М-{rng.randint(3000, 3999)}/25",
                   "court_name": c["court_name"], "plaintiffs": c["plaintiffs"], "legal_entity": c["legal_entity"],
                   "complex": c["complex"], "building": c["building"], "flat": c["flat"], "subject": c["subject"],
                   "stage": "иск"}])

    for t in ("ocr", "fetch_letter", "classify_act"):
        ld.create_task(t, {"pilot": True})

    print(f"Готово: дел {len(cases) + len(dups)}, актов {n_docs}, документов без дела 8, дублей {len(dups)}, "
          f"календарь {today.year}–{today.year + 1}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
