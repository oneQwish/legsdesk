@echo off
rem Остановить пилот (данные сохраняются до следующего запуска).
cd /d "%~dp0"
docker compose stop
