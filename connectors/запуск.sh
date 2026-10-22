#!/bin/sh
# Запуск всех подключений из папки «подключения» по очереди (Linux/macOS; для cron).
# Пример строки cron (каждый час):  0 * * * * /opt/lawdesk/connectors/запуск.sh
# Пароли и ключ — в файле «секреты.sh» рядом (создайте из «секреты.пример.sh»).
cd "$(dirname "$0")" || exit 2
[ -f ./секреты.sh ] && . ./секреты.sh
RESULT=0
for f in подключения/*.toml; do
    [ -e "$f" ] || continue
    python3 lawdesk_connect.py запустить "$f" || RESULT=1
done
exit $RESULT
