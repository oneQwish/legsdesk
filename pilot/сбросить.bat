@echo off
rem Удалить пилот вместе с данными: следующий запуск начнётся с чистыми тестовыми данными.
chcp 65001 >nul
cd /d "%~dp0"
set /p OK=Удалить все данные пилота? (да/нет): 
if /i not "%OK%"=="да" exit /b 0
docker compose down -v
