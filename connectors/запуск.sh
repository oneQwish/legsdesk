#!/bin/sh
# Запуск всех подключений из папки «подключения» по очереди (Linux/macOS; для cron).
# Пример строки cron (каждый час):  0 * * * * /opt/lawdesk/connectors/запуск.sh
# Пароли и ключ — в файле «секреты.sh» рядом (создайте из «секреты.пример.sh»).
cd "$(dirname "$0")" || exit 2
[ -f ./секреты.sh ] && . ./секреты.sh
RESULT=0
for f in подключения/*.toml; do
    [ -e "$f" ] || continue
    python3 lawdesk_connect.py запустить "$f"
    CODE=$?
    [ "$CODE" -gt "$RESULT" ] && RESULT=$CODE   # наибольший код: 1 строки, 2 настройки, 3 связь, 4 уже идёт, 5 сбой
done
exit $RESULT
