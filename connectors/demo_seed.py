"""Демо-данные для пробы рабочего места (вымышленные люди и дела, без персональных данных).

1) создаёт синтетическую sot.db (та же форма, что ожидает sot_sync.py) — проверка коннектора;
2) отправляет её через sot_sync;
3) добавляет документы с файлами (простые PDF), акты и сроки, пару задач в очередь.

    LAWDESK_KEY=ldk_... python demo_seed.py --url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lawdesk_client import Lawdesk  # noqa: E402

SURNAMES = ["Орлов", "Соколова", "Ветров", "Лебедева", "Морозов", "Зайцева", "Ковалёв", "Белова", "Громов", "Тихонова",
            "Журавлёв", "Миронова", "Сазонов", "Крылова", "Фомин", "Полякова"]
JUDGES = ["Пономарёва Е.В.", "Кудрявцев А.С.", "Аксёнова Т.Н.", "Рябинин О.Г."]
COURTS = [("000000123", "Железнодорожный городской суд Московской области", "50RS0010"),
          ("000000456", "Балашихинский городской суд Московской области", "50RS0001"),
          ("000000789", "Перовский районный суд г. Москвы", "77RS0020")]
BUILDINGS = [("401", "ЖК Героев", "ГС-Саввино"), ("308", "ЖК Героев", "ГС-Саввино"), ("23", "ЖК Столичный", "ГС-Столичный"),
             ("Б2", "ЖК Столичный (Юг)", "ГС-СПб")]


def initials(rng):
    return f"{rng.choice('АБВГДЕИКМНОПС')}.{rng.choice('АБВГДЕИКМНОПС')}."


def make_sot(path: Path, n: int, seed: int = 7) -> None:
    rng = random.Random(seed)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE cases(case_id INTEGER PRIMARY KEY, court TEXT, court_name TEXT, case_key TEXT, entity TEXT,
                           complex TEXT, building TEXT, flat TEXT, contract_no TEXT, plaintiffs TEXT, subject TEXT,
                           status TEXT, outcome TEXT, appeal_possible INTEGER);
        CREATE TABLE case_aliases(case_id INTEGER, court TEXT, case_key TEXT);
        CREATE TABLE case_uid(case_id INTEGER, uid TEXT);
        CREATE TABLE case_values(case_id INTEGER, field TEXT, status TEXT, sources TEXT);
    """)
    for i in range(1, n + 1):
        code, cname, ucode = rng.choice(COURTS)
        b, cx, ent = rng.choice(BUILDINGS)
        year = rng.choice([2023, 2024, 2025])
        num = f"2-{rng.randint(100, 9999)}/{year % 100}"
        flat = str(rng.randint(1, 400))
        pl = "; ".join(f"{rng.choice(SURNAMES)} {initials(rng)}" for _ in range(rng.choice([1, 1, 2])))
        subj = rng.choice(["недостатки", "неустойка за просрочку", "уменьшение цены"])
        con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (i, code, cname, num, ent, cx, b, flat, f"АВТ{b}-01-0{rng.randint(1,9)}-0{rng.randint(1,9)}-{flat.zfill(3)}",
                     pl, subj, "рассмотрено", "удовлетворён частично", int(rng.random() < .1)))
        if rng.random() < .3:
            con.execute("INSERT INTO case_aliases VALUES (?,?,?)", (i, code, f"М-{rng.randint(100, 3000)}/{year % 100}"))
        if rng.random() < .8:
            con.execute("INSERT INTO case_uid VALUES (?,?)", (i, f"{ucode}-01-{year}-{rng.randint(1, 15000):06d}-{rng.randint(10, 99)}"))
        debt = round(rng.uniform(60_000, 900_000), 2)
        pen = round(rng.uniform(10_000, 300_000), 2)
        judge = rng.choice(JUDGES)
        dd = date(year, 1, 1) + timedelta(days=rng.randint(30, 330))
        rows = {
            "судья": {"1c": judge, "otchet": judge, "letter": judge if rng.random() < .9 else rng.choice(JUDGES)},
            "истцы": {"1c": pl, "ocr": pl},
            "дата решения": {"otchet": dd.isoformat(), "letter": dd.strftime("%d.%m.%Y")},
            "долг": {"otchet": debt * (2 if rng.random() < .15 else 1), "ocr": debt, "letter": debt},
            "неустойка": {"otchet": pen, "ocr": pen if rng.random() < .85 else round(pen / 10, 2)},
            "штраф": {"otchet": round((debt + pen) / 4, 2), "ocr": round((debt + pen) / 4, 2)},
            "кмв": {"otchet": 10000, "letter": rng.choice([5000, 10000])},
        }
        for f, src in rows.items():
            con.execute("INSERT INTO case_values VALUES (?,?,?,?)", (i, f, "", json.dumps(src, ensure_ascii=False)))
    con.commit()
    con.close()


def tiny_pdf(title: str) -> bytes:
    """Минимальный одностраничный PDF (латиница — базовый шрифт без кириллицы)."""
    text = title.encode("ascii", "replace").decode()
    stream = f"BT /F1 18 Tf 72 760 Td ({text}) Tj ET BT /F1 11 Tf 72 730 Td (Demo document - synthetic data) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % x for x in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("LAWDESK_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--key", default=os.environ.get("LAWDESK_KEY"))
    ap.add_argument("--cases", type=int, default=60)
    a = ap.parse_args()
    if not a.key:
        raise SystemExit("Нужен ключ: --key или LAWDESK_KEY (области read, ingest, tasks)")

    tmp = Path(tempfile.mkdtemp()) / "sot_demo.db"
    make_sot(tmp, a.cases)
    subprocess.run([sys.executable, str(Path(__file__).parent / "sot_sync.py"), "--db", str(tmp), "--url", a.url, "--key", a.key], check=True)

    ld = Lawdesk(a.url, a.key)
    rng = random.Random(11)
    today = date.today()
    cases = ld.find_cases("", size=500)["items"]
    for c in cases[: min(25, len(cases))]:
        ref = {"case_id": c["id"]}
        dec = today - timedelta(days=rng.randint(12, 45))
        motivated = dec + timedelta(days=rng.randint(3, 10))
        title = f"Reshenie {c['case_number']}"
        meta = {"kind": rng.choice(["письмо", "скан"]), "act_type": "решение", "instance": "первая",
                "act_date": dec.isoformat(), "motivated_date": motivated.isoformat() if rng.random() < .8 else None,
                "text": f"РЕШЕНИЕ\nИменем Российской Федерации\n{c['court_name']}\nДело № {c['case_number']}\n"
                        f"Истцы: {c['plaintiffs']}\n...\nРЕШИЛ: иск удовлетворить частично.\n(синтетический текст)",
                "text_source": "цифровой", "case": ref, "track_no": f"8021{rng.randint(10**9, 10**10 - 1)}"}
        p = Path(tempfile.mkdtemp()) / f"{c['id']}_решение.pdf"
        p.write_bytes(tiny_pdf(title))
        ld.upload(p, meta)
        if rng.random() < .4:
            p2 = Path(tempfile.mkdtemp()) / f"{c['id']}_определение.pdf"
            p2.write_bytes(tiny_pdf(f"Opredelenie {c['case_number']}"))
            ld.upload(p2, {"kind": "письмо", "act_type": "определение о судебных расходах", "instance": "первая",
                           "act_date": (today - timedelta(days=rng.randint(1, 12))).isoformat(), "case": ref,
                           "text": "ОПРЕДЕЛЕНИЕ о взыскании судебных расходов (синтетический текст)", "text_source": "цифровой"})
    for t in ("ocr", "fetch_letter", "classify_act"):
        ld.create_task(t, {"demo": True})
    print("Готово: демо-дела, документы, сроки и задачи загружены.")


if __name__ == "__main__":
    main()
