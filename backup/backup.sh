#!/bin/sh
# =================================================================================================
#  Резервные копии lawdesk: база PostgreSQL + файлы документов.
#
#  Как запускается:
#    backup.sh            — работать постоянно: раз в сутки в BACKUP_TIME делать копию (так его
#                           запускает контейнер backup);
#    backup.sh now        — сделать копию прямо сейчас и выйти;
#    backup.sh check      — только проверить, что последняя копия базы восстанавливается;
#    backup.sh list       — показать копии (и какие удалит следующее прореживание) и статус;
#    backup.sh selftest   — проверить правила прореживания на вымышленных именах файлов
#                           (база не нужна, ничего не удаляет).
#
#  Что делает одна копия (по порядку):
#    1) проверяет свободное место (BACKUP_MIN_FREE_MB);
#    2) pg_dump -Fc базы → db/lawdesk_ГГГГ-ММ-ДД_ЧЧММ.dump (сначала .partial, потом переименование;
#       файл проверяется командой pg_restore --list);
#    3) архив файлов документов → storage/storage_ГГГГ-ММ-ДД.tar.gz (если папка есть; проверка gzip -t);
#    4) проверка восстановления: свежий дамп разворачивается во временную базу и сверяется число
#       строк в таблицах CHECK_TABLES с рабочей базой; временная база удаляется;
#    5) прореживание старых копий (см. prune_plan ниже);
#    6) итог — в status.json (его показывает страница администратора).
#
#  Аналогия с 1С: это «регламентное задание» выгрузки в .dt плюс копия каталога файлов,
#  с проверкой, что выгрузка загружается.
# =================================================================================================

set -u
umask 077   # копии содержат персональные данные — читать их может только root

# ---- Настройки: всё можно задать переменными окружения -------------------------------------------
BACKUP_TIME=${BACKUP_TIME:-02:30}                # когда делать копию (ЧЧ:ММ, часовой пояс — TZ)
BACKUP_DIR=${BACKUP_DIR:-/backups}               # куда класть копии
STORAGE_DIR=${STORAGE_DIR:-/data/storage}        # том с файлами документов (только чтение)
BACKUP_MIN_FREE_MB=${BACKUP_MIN_FREE_MB:-2048}   # меньше свободного места — копию не делать
KEEP_DAYS=${KEEP_DAYS:-30}                       # хранить все копии за столько дней
KEEP_WEEKS=${KEEP_WEEKS:-12}                     # ... и по одной последней на неделю за столько недель
KEEP_MONTHS=${KEEP_MONTHS:-12}                   # ... и по одной последней на месяц за столько месяцев
DB_NAME=${DB_NAME:-lawdesk}                      # рабочая база
RESTORE_DB=${RESTORE_DB:-lawdesk_restore_check}  # временная база для проверки восстановления
MAINT_DB=${MAINT_DB:-postgres}                   # служебная база, из которой создаём/удаляем временную
CHECK_TABLES=${CHECK_TABLES:-cases documents events}

export PGHOST="${PGHOST:-db}" PGPORT="${PGPORT:-5432}" PGUSER="${PGUSER:-lawdesk}"
if [ -z "${PGPASSWORD:-}" ] && [ -n "${POSTGRES_PASSWORD:-}" ]; then
    export PGPASSWORD="$POSTGRES_PASSWORD"
fi

DB_DIR="$BACKUP_DIR/db"
ST_DIR="$BACKUP_DIR/storage"
STATUS_FILE="$BACKUP_DIR/status.json"
LOCK_DIR="$BACKUP_DIR/.lock"
ERR_FILE="$BACKUP_DIR/.last_error.txt"

# ---- Мелкие помощники ----------------------------------------------------------------------------
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

# Текущее время в ISO 8601 с часовым поясом: 2026-10-25T02:30:00+03:00
iso_now() {
    _d=$(date +%Y-%m-%dT%H:%M:%S%z)
    _z=${_d#"${_d%?????}"}            # последние 5 символов: +0300
    echo "${_d%?????}${_z%??}:${_z#???}"
}

# Строка для JSON: в кавычках, с экранированием; пустая строка → null
jstr() {
    if [ -z "$1" ]; then echo null; return; fi
    printf '"%s"' "$(printf '%s' "$1" | tr '\n\r\t' '   ' | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g')"
}

add_err() {
    log "ОШИБКА: $*"
    if [ -z "$ERRORS" ]; then ERRORS="$*"; else ERRORS="$ERRORS; $*"; fi
}

# Последние строки текста ошибки команды (для status.json — коротко)
err_tail() { [ -s "$ERR_FILE" ] && tail -n 5 "$ERR_FILE" | tr '\n' ' ' | cut -c1-500; }

# Свободное место (МБ) на диске с копиями
free_mb() { df -Pk "$BACKUP_DIR" 2>/dev/null | awk 'NR==2 {print int($4/1024)}'; }

# Номер дня от 01.01.1970 для даты ГГГГ-ММ-ДД (чистая арифметика, без команды date)
days_of() {
    _y=${1%%-*}; _r=${1#*-}; _m=${_r%%-*}; _dd=${_r#*-}
    _m=$((1$_m - 100)); _dd=$((1$_dd - 100))     # «08» → 8 (иначе посчитается восьмеричным)
    _y=$((_y - (_m <= 2)))
    _era=$((_y / 400)); _yoe=$((_y - _era * 400))
    _mp=$((_m > 2 ? _m - 3 : _m + 9))
    _doy=$(((153 * _mp + 2) / 5 + _dd - 1))
    echo $((_era * 146097 + _yoe * 365 + _yoe / 4 - _yoe / 100 + _doy - 719468))
}

# Обратное: номер дня → ГГГГ-ММ-ДД (нужно только для selftest)
date_of() {
    _z=$(($1 + 719468)); _era=$((_z / 146097)); _doe=$((_z - _era * 146097))
    _yoe=$(((_doe - _doe / 1460 + _doe / 36524 - _doe / 146096) / 365))
    _y=$((_yoe + _era * 400)); _doy=$((_doe - (365 * _yoe + _yoe / 4 - _yoe / 100)))
    _mp=$(((5 * _doy + 2) / 153)); _dd=$((_doy - (153 * _mp + 2) / 5 + 1))
    _m=$((_mp < 10 ? _mp + 3 : _mp - 9)); _y=$((_y + (_m <= 2)))
    printf '%04d-%02d-%02d\n' "$_y" "$_m" "$_dd"
}

# ---- Прореживание ---------------------------------------------------------------------------------
# На входе — имена файлов копий (по одному в строке), $1 — сегодняшняя дата ГГГГ-ММ-ДД.
# На выходе — строки «keep ИМЯ причина» или «delete ИМЯ». Сами файлы здесь не трогаются.
# Правила (идём от свежих к старым):
#   - самая свежая копия остаётся всегда;
#   - все копии моложе KEEP_DAYS дней остаются;
#   - самая свежая копия каждой недели (пн–вс) остаётся, если ей меньше KEEP_WEEKS недель;
#   - самая свежая копия каждого месяца остаётся, если месяц — один из последних KEEP_MONTHS;
#   - файлы с непонятным именем не удаляются никогда.
prune_plan() {
    _t=$(days_of "$1")
    _ty=${1%%-*}; _tm=${1#*-}; _tm=${_tm%%-*}; _tmi=$((_ty * 12 + 1$_tm - 100))
    _first=1; _weeks=" "; _months=" "
    sort -r | while IFS= read -r _f; do
        [ -n "$_f" ] || continue
        _ds=${_f#*_}; _ds=${_ds%%[_.]*}          # lawdesk_2026-10-25_0230.dump → 2026-10-25
        case $_ds in
            [0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]) ;;
            *) echo "keep $_f непонятное_имя"; continue ;;
        esac
        _n=$(days_of "$_ds")
        _age=$((_t - _n))
        _wk=$((_n - (_n + 3) % 7))                # день-понедельник этой недели (01.01.1970 — четверг)
        _y=${_ds%%-*}; _mm=${_ds#*-}; _mm=${_mm%%-*}; _mi=$((_y * 12 + 1$_mm - 100))
        _why=""
        [ "$_first" = 1 ] && _why="самая_свежая"
        [ -z "$_why" ] && [ "$_age" -lt "$KEEP_DAYS" ] && _why="последние_${KEEP_DAYS}_дней"
        case $_weeks in *" $_wk "*) ;; *)
            [ -z "$_why" ] && [ "$_age" -lt $((KEEP_WEEKS * 7)) ] && _why="неделя"
            _weeks="$_weeks$_wk " ;;
        esac
        case $_months in *" $_mi "*) ;; *)
            [ -z "$_why" ] && [ $((_tmi - _mi)) -lt "$KEEP_MONTHS" ] && _why="месяц"
            _months="$_months$_mi " ;;
        esac
        _first=0
        if [ -n "$_why" ]; then echo "keep $_f $_why"; else echo "delete $_f"; fi
    done
}

# Имена файлов копий в папке $1 по шаблону $2 (без .partial)
list_names() {
    for _p in "$1"/$2; do [ -f "$_p" ] && echo "${_p##*/}"; done
}

# Прореживание папки: $1 — папка, $2 — шаблон имён
prune_dir() {
    list_names "$1" "$2" | prune_plan "$(date +%Y-%m-%d)" | while read -r _act _name _why; do
        if [ "$_act" = delete ]; then
            rm -f "$1/$_name" && log "удалена старая копия $_name"
        fi
    done
}

count_db_copies() { list_names "$DB_DIR" "${DB_NAME}_*.dump" | wc -l | tr -d ' '; }
latest_db_copy() { list_names "$DB_DIR" "${DB_NAME}_*.dump" | sort | tail -n 1; }

# ---- Блокировка: две копии одновременно не делаем --------------------------------------------------
take_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then echo $$ > "$LOCK_DIR/pid"; return 0; fi
    _pid=$(cat "$LOCK_DIR/pid" 2>/dev/null)
    if [ -n "$_pid" ] && kill -0 "$_pid" 2>/dev/null; then
        log "Уже идёт другая копия или проверка (процесс $_pid). Подождите."
        return 1
    fi
    rm -rf "$LOCK_DIR"                           # остался от прерванного запуска
    mkdir "$LOCK_DIR" 2>/dev/null && echo $$ > "$LOCK_DIR/pid"
}
release_lock() {
    [ "$(cat "$LOCK_DIR/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCK_DIR"
    return 0
}

# ---- Шаги копии -----------------------------------------------------------------------------------
# 1. Дамп базы. Успех → DB_FILE, DB_SIZE.
do_dump() {
    _out="$DB_DIR/${DB_NAME}_$(date +%Y-%m-%d_%H%M).dump"
    _tmp="$_out.partial"
    rm -f "$_tmp"
    log "дамп базы $DB_NAME → $_out"
    if ! pg_dump -Fc -d "$DB_NAME" -f "$_tmp" 2>"$ERR_FILE"; then
        add_err "pg_dump не удался: $(err_tail)"; rm -f "$_tmp"; return 1
    fi
    if [ ! -s "$_tmp" ] || ! pg_restore --list "$_tmp" >/dev/null 2>"$ERR_FILE"; then
        add_err "файл дампа не читается (pg_restore --list): $(err_tail)"; rm -f "$_tmp"; return 1
    fi
    mv -f "$_tmp" "$_out"
    DB_FILE=$_out
    DB_SIZE=$(wc -c < "$_out" | tr -d ' ')
    log "дамп готов: $DB_SIZE байт"
}

# 2. Архив файлов документов (если том смонтирован). Успех → ST_FILE.
do_storage() {
    if [ ! -d "$STORAGE_DIR" ]; then
        log "папки $STORAGE_DIR нет — файлы документов не копируем (хранилище не локальное?)"
        return 0
    fi
    _out="$ST_DIR/storage_$(date +%Y-%m-%d).tar.gz"
    _tmp="$_out.partial"
    rm -f "$_tmp"
    log "архив файлов $STORAGE_DIR → $_out"
    if ! tar -czf "$_tmp" -C "$STORAGE_DIR" . 2>"$ERR_FILE"; then
        add_err "архив файлов не удался: $(err_tail)"; rm -f "$_tmp"; return 1
    fi
    if ! gzip -t "$_tmp" 2>"$ERR_FILE"; then
        add_err "архив файлов повреждён (gzip -t): $(err_tail)"; rm -f "$_tmp"; return 1
    fi
    mv -f "$_tmp" "$_out"
    ST_FILE=$_out
    log "архив файлов готов: $(wc -c < "$_out" | tr -d ' ') байт"
}

# 3. Проверка восстановления дампа $1. Итог → RC_OK (true/false), RC_DETAILS.
restore_check() {
    RC_OK=false
    case $RESTORE_DB in
        "" | "$DB_NAME" | postgres | template0 | template1)
            RC_DETAILS="RESTORE_DB=«$RESTORE_DB» нельзя: временная база не должна совпадать с рабочей или служебной"
            return 1 ;;
    esac
    log "проверка восстановления ${1##*/} во временную базу $RESTORE_DB"
    _q="psql -X -q -At -v ON_ERROR_STOP=1"
    if ! $_q -d "$MAINT_DB" -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\" WITH (FORCE)" \
            -c "CREATE DATABASE \"$RESTORE_DB\"" >/dev/null 2>"$ERR_FILE"; then
        RC_DETAILS="не удалось создать временную базу: $(err_tail)"; return 1
    fi
    if ! pg_restore --no-owner -d "$RESTORE_DB" "$1" 2>"$ERR_FILE"; then
        RC_DETAILS="pg_restore с ошибками: $(err_tail)"
    else
        RC_OK=true; RC_DETAILS=""
        for _tb in $CHECK_TABLES; do
            _c=$($_q -d "$RESTORE_DB" -c "SELECT count(*) FROM $_tb" 2>"$ERR_FILE") || { RC_OK=false; _c="?"; }
            _p=$($_q -d "$DB_NAME" -c "SELECT count(*) FROM $_tb" 2>>"$ERR_FILE") || { RC_OK=false; _p="?"; }
            _note=""
            if [ "$_c" = "?" ] || [ "$_p" = "?" ]; then
                _note=" — ошибка: $(err_tail)"
            elif [ "$_p" -gt 0 ] && [ "$_c" -eq 0 ]; then
                RC_OK=false; _note=" — в копии нет строк"
            elif [ $((_p * 100)) -lt $((_c * 99)) ]; then
                RC_OK=false; _note=" — в рабочей базе меньше строк, чем в копии, более чем на 1%"
            fi
            RC_DETAILS="${RC_DETAILS:+$RC_DETAILS; }$_tb: копия $_c, рабочая $_p$_note"
        done
    fi
    $_q -d "$MAINT_DB" -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\" WITH (FORCE)" >/dev/null 2>&1 \
        || log "не удалось удалить временную базу $RESTORE_DB"
    log "проверка восстановления: $([ "$RC_OK" = true ] && echo успешно || echo НЕ ПРОШЛА) ($RC_DETAILS)"
    [ "$RC_OK" = true ]
}

# 4. Запись status.json (атомарно: во временный файл и переименование)
write_status() {
    _prev_ok=$(sed -n 's/^ *"last_ok": *"\([^"]*\)".*/\1/p' "$STATUS_FILE" 2>/dev/null | head -n 1)
    [ "$OK" = true ] && _prev_ok=$RUN_AT
    _tmp="$STATUS_FILE.tmp"
    cat > "$_tmp" <<EOF
{
  "last_run": $(jstr "$RUN_AT"),
  "last_ok": $(jstr "$_prev_ok"),
  "ok": $OK,
  "db_file": $(jstr "${DB_FILE##*/}"),
  "db_size": ${DB_SIZE:-0},
  "storage_file": $(jstr "${ST_FILE##*/}"),
  "restore_check": {"ok": $RC_OK, "details": $(jstr "$RC_DETAILS")},
  "error": $(jstr "$ERRORS"),
  "kept": ${KEPT:-0},
  "free_mb": ${FREE:-0},
  "backup_time": $(jstr "$BACKUP_TIME")
}
EOF
    chmod 644 "$_tmp"   # статус читает сервер приложения (там нет паролей и данных)
    mv -f "$_tmp" "$STATUS_FILE"
}

# Полная копия. Возвращает 0, если всё прошло без ошибок.
run_backup() {
    ERRORS=""; DB_FILE=""; DB_SIZE=0; ST_FILE=""; RC_OK=false; RC_DETAILS="не выполнялась"
    RUN_AT=$(iso_now)
    mkdir -p "$DB_DIR" "$ST_DIR"
    chmod 755 "$BACKUP_DIR"   # сервер приложения (не root) должен прочитать status.json; db/ и storage/ закрыты
    rm -f "$DB_DIR"/*.partial "$ST_DIR"/*.partial    # остатки прерванных запусков
    FREE=$(free_mb); FREE=${FREE:-0}
    log "=== резервная копия: свободно $FREE МБ ==="
    if [ "$FREE" -lt "$BACKUP_MIN_FREE_MB" ]; then
        add_err "мало места: свободно $FREE МБ, нужно не меньше $BACKUP_MIN_FREE_MB МБ (BACKUP_MIN_FREE_MB) — копия не сделана"
    else
        _dump_ok=false; _st_ok=false
        do_dump && _dump_ok=true
        do_storage && _st_ok=true
        if [ "$_dump_ok" = true ]; then
            restore_check "$DB_FILE" || add_err "проверка восстановления не прошла: $RC_DETAILS"
            prune_dir "$DB_DIR" "${DB_NAME}_*.dump"           # старые удаляем, только если новая есть
            [ "$_st_ok" = true ] && [ -n "$ST_FILE" ] && prune_dir "$ST_DIR" "storage_*.tar.gz"
        fi
    fi
    rm -f "$ERR_FILE"
    KEPT=$(count_db_copies)
    FREE=$(free_mb); FREE=${FREE:-0}
    if [ -z "$ERRORS" ]; then OK=true; else OK=false; fi
    write_status
    log "=== итог: $([ "$OK" = true ] && echo успешно || echo С ОШИБКАМИ), копий базы: $KEPT, свободно $FREE МБ ==="
    [ "$OK" = true ]
}

# ---- Команды ---------------------------------------------------------------------------------------
cmd_daemon() {
    case $BACKUP_TIME in
        [01][0-9]:[0-5][0-9] | 2[0-3]:[0-5][0-9]) ;;
        *) log "BACKUP_TIME=«$BACKUP_TIME»: нужно время вида ЧЧ:ММ, например 02:30"; exit 2 ;;
    esac
    mkdir -p "$BACKUP_DIR"
    rm -rf "$LOCK_DIR"                           # после перезапуска контейнера других запусков нет
    trap 'release_lock; log "остановлен"; exit 0' INT TERM
    # Дата последней копии — из status.json, чтобы после перезапуска не делать вторую за день,
    # а если сервер был выключен в BACKUP_TIME — сделать пропущенную сразу.
    _last_day=$(sed -n 's/^ *"last_run": *"\([0-9-]\{10\}\).*/\1/p' "$STATUS_FILE" 2>/dev/null | head -n 1)
    log "контейнер копий запущен: копия ежедневно в $BACKUP_TIME (TZ=${TZ:-не задан}), база $DB_NAME на $PGHOST:$PGPORT, папка $BACKUP_DIR"
    log "последняя копия: ${_last_day:-ещё не было}"
    _target=${BACKUP_TIME%:*}${BACKUP_TIME#*:}  # 02:30 → 0230
    while :; do
        _today=$(date +%Y-%m-%d)
        # Сегодня копии ещё не было и время уже наступило (ЧЧММ сравниваем как числа)
        if [ "$_today" != "$_last_day" ] && [ "$(date +%H%M)" -ge "$_target" ]; then
            _last_day=$_today
            if take_lock; then
                run_backup
                release_lock
            fi
        fi
        sleep 20 &
        wait $!
    done
}

cmd_now() {
    mkdir -p "$BACKUP_DIR"
    take_lock || exit 1
    trap 'release_lock' EXIT
    trap 'exit 1' INT TERM
    run_backup
}

cmd_check() {
    _f=$(latest_db_copy)
    if [ -z "$_f" ]; then echo "Копий базы в $DB_DIR нет."; exit 1; fi
    take_lock || exit 1
    trap 'release_lock' EXIT
    trap 'exit 1' INT TERM
    restore_check "$DB_DIR/$_f"
    _rc=$?
    rm -f "$ERR_FILE"
    echo "Копия: $_f"
    echo "Восстановление: $([ $_rc = 0 ] && echo успешно || echo НЕ ПРОШЛО)"
    echo "Подробности: $RC_DETAILS"
    exit $_rc
}

cmd_list() {
    _today=$(date +%Y-%m-%d)
    for _pair in "$DB_DIR|${DB_NAME}_*.dump" "$ST_DIR|storage_*.tar.gz"; do
        _d=${_pair%%|*}; _pat=${_pair#*|}
        echo "== $_d"
        list_names "$_d" "$_pat" | prune_plan "$_today" | sort -k2 | while read -r _act _name _why; do
            _sz=$(wc -c < "$_d/$_name" | tr -d ' ')
            if [ "$_act" = keep ]; then _act="хранится ($_why)"; else _act="будет удалена при следующей копии"; fi
            printf '  %-36s %12s байт  %s\n' "$_name" "$_sz" "$_act"
        done
    done
    echo "== свободно: $(free_mb) МБ"
    echo "== $STATUS_FILE:"
    cat "$STATUS_FILE" 2>/dev/null || echo "  (ещё нет — копий не было)"
}

# Самопроверка правил прореживания на вымышленных именах (ничего не удаляет, база не нужна).
cmd_selftest() {
    _fail=0
    _check() { if [ "$2" = "$3" ]; then echo "  да:  $1 ($2)"; else echo "  НЕТ: $1 — ждали $3, получили $2"; _fail=1; fi; }
    _today=2026-10-25; _t=$(days_of $_today)

    echo "Перевод дат туда и обратно:"
    for _d in 1970-01-01 2000-02-29 2024-12-31 2026-03-01 2026-10-25; do
        _check "$_d" "$(date_of "$(days_of $_d)")" "$_d"
    done

    echo "Набор 1: копия каждый день за 500 дней (+ две ручные сегодня и вчера), сегодня $_today:"
    _plan=$( {
        _i=0; while [ $_i -lt 500 ]; do echo "lawdesk_$(date_of $((_t - _i)))_0230.dump"; _i=$((_i + 1)); done
        echo "lawdesk_${_today}_1415.dump"; echo "lawdesk_$(date_of $((_t - 1)))_1700.dump"
        echo "lawdesk_мусор.dump"
    } | prune_plan $_today)
    _check "самая свежая остаётся" "$(echo "$_plan" | grep -c "^keep lawdesk_${_today}_1415.dump самая_свежая")" 1
    _check "за 30 дней все (30 + 2 ручные)" "$(echo "$_plan" | grep -c '^keep .*последние_30_дней')" 31
    # недели старше 30 дней: понедельники до 84 дней; 2026-10-25 — воскресенье, поэтому
    # «последняя копия недели» — воскресенье; дни 35,42,...,77 → 7 копий
    _check "по неделям (возраст 30–83 дня)" "$(echo "$_plan" | grep -c '^keep .*неделя')" 7
    # месяцы: последние 12 (ноябрь 2025 – октябрь 2026), последняя копия месяца = его последний день;
    # сентябрь и октябрь уже в «30 днях», остальные: ноябрь 2025 … август 2026 = 10 копий
    # (31 августа — понедельник, «неделей» он не остался, поэтому остаётся «месяцем»)
    _check "по месяцам" "$(echo "$_plan" | grep -c '^keep .*месяц')" 10
    _check "непонятное имя не удаляется" "$(echo "$_plan" | grep -c '^keep lawdesk_мусор.dump непонятное_имя')" 1
    _check "старше 12 месяцев ничего" "$(echo "$_plan" | grep '^keep lawdesk_2025-0' | wc -l | tr -d ' ')" 0
    _check "31.07.2026 остаётся как месяц" "$(echo "$_plan" | grep -c '^keep lawdesk_2026-07-31_0230.dump месяц')" 1
    _check "30.07.2026 удаляется" "$(echo "$_plan" | grep -c '^delete lawdesk_2026-07-30_0230.dump')" 1
    _check "всего удалить" "$(echo "$_plan" | grep -c '^delete')" $((502 - 1 - 31 - 7 - 10))

    echo "Набор 2: только очень старые копии (сервер копий долго не работал):"
    _plan=$(printf '%s\n' storage_2023-01-10.tar.gz storage_2023-05-01.tar.gz storage_2024-02-02.tar.gz | prune_plan $_today)
    _check "самая свежая из старых остаётся" "$(echo "$_plan" | grep -c '^keep storage_2024-02-02.tar.gz')" 1
    _check "остальные удаляются" "$(echo "$_plan" | grep -c '^delete')" 2

    echo "Набор 3: пусто:"
    _check "пустой список — пустой план" "$(printf '' | prune_plan $_today | wc -l | tr -d ' ')" 0

    if [ $_fail = 0 ]; then echo "Самопроверка пройдена."; else echo "Самопроверка НЕ пройдена."; fi
    exit $_fail
}

case ${1:-daemon} in
    daemon) cmd_daemon ;;
    now) cmd_now ;;
    check) cmd_check ;;
    list) cmd_list ;;
    selftest) cmd_selftest ;;
    *) echo "Использование: backup.sh [now|check|list|selftest]  (без параметра — работать по расписанию)"; exit 2 ;;
esac
