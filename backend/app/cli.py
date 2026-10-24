"""Служебные команды.

  python -m app.cli init-db
  python -m app.cli настройки                  → проверить settings.toml и показать итоговые значения
  python -m app.cli service NAME --scopes read,ingest,tasks --task-types ocr,extract   → печатает API-ключ
"""
import argparse

from sqlalchemy import select

from .config import SECRETS, SECTIONS, SettingsFileError, describe_sources, get_settings, problems, settings_path


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="Создать таблицы")
    sub.add_parser("настройки", aliases=["settings"], help="Проверить файл настроек и показать итоговые значения")
    s = sub.add_parser("service", help="Создать сервис (или взять существующий) и выдать новый API-ключ")
    s.add_argument("name")
    s.add_argument("--scopes", default="read,ingest")
    s.add_argument("--task-types", default="")
    s.add_argument("--description", default="")
    a = p.parse_args()

    if a.cmd in ("настройки", "settings"):
        raise SystemExit(show_settings())

    from .db import SessionLocal, init_db
    from .models import Service
    from .security import SCOPES, issue_api_key

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


def show_settings() -> int:
    """Итоговые настройки по разделам и откуда взято значение. Секреты не показываются. Код 1 — есть ошибки."""
    try:
        s = get_settings()
    except SettingsFileError as e:
        print(f"ОШИБКА: {e}")
        return 1
    src = describe_sources()
    print(f"Файл настроек: {settings_path()}{'' if settings_path().exists() else ' (нет — действуют умолчания)'}")
    for section, keys in SECTIONS.items():
        print(f"\n[{section}]")
        for k in keys:
            print(f"  {k:<28} = {getattr(s, k)!r:<40} ({src[k]})")
    print("\n[секреты — только окружение / .env]")
    for k in sorted(SECRETS):
        print(f"  {k:<28} {'задан' if src[k] == 'окружение' else 'НЕ задан (умолчание)'}")
    bad = problems(s)
    for b in bad:
        print(f"ОШИБКА: {b}")
    print("\nВсё в порядке." if not bad else f"\nОшибок: {len(bad)} — сервер с такими настройками не стартует.")
    return 1 if bad else 0


if __name__ == "__main__":
    main()
