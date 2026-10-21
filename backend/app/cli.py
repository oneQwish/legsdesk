"""Служебные команды.

  python -m app.cli init-db
  python -m app.cli service NAME --scopes read,ingest,tasks --task-types ocr,extract   → печатает API-ключ
"""
import argparse

from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import Service
from .security import SCOPES, issue_api_key


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="Создать таблицы")
    s = sub.add_parser("service", help="Создать сервис (или взять существующий) и выдать новый API-ключ")
    s.add_argument("name")
    s.add_argument("--scopes", default="read,ingest")
    s.add_argument("--task-types", default="")
    s.add_argument("--description", default="")
    a = p.parse_args()

    init_db()
    if a.cmd == "service":
        scopes = [x for x in a.scopes.split(",") if x]
        bad = set(scopes) - SCOPES.keys()
        if bad:
            raise SystemExit(f"Неизвестные области: {bad}; доступны {list(SCOPES)}")
        with SessionLocal() as db:
            svc = db.scalar(select(Service).where(Service.name == a.name))
            if svc is None:
                svc = Service(name=a.name, description=a.description, scopes=scopes,
                              task_types=[x for x in a.task_types.split(",") if x])
                db.add(svc)
                db.flush()
            key = issue_api_key(db, svc)
            db.commit()
            print(key)


if __name__ == "__main__":
    main()
