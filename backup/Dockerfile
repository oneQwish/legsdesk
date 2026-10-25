# Контейнер резервных копий: тот же PostgreSQL 16, что и в db (в нём уже есть pg_dump, pg_restore, psql).
# Сам сервер PostgreSQL здесь не запускается — только скрипт backup.sh по расписанию.
FROM postgres:16-alpine
# tzdata — чтобы время копии (BACKUP_TIME) считалось по TZ=Europe/Moscow
RUN apk add --no-cache tzdata && mkdir -p /backups
COPY backup.sh /usr/local/bin/backup.sh
RUN chmod 755 /usr/local/bin/backup.sh
ENV TZ=Europe/Moscow BACKUP_TIME=02:30 BACKUP_DIR=/backups STORAGE_DIR=/data/storage \
    PGHOST=db PGPORT=5432 PGUSER=lawdesk DB_NAME=lawdesk
ENTRYPOINT ["/usr/local/bin/backup.sh"]
CMD ["daemon"]
