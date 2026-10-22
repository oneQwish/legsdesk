@echo off
rem Пилот рабочего места юриста: собрать, запустить, загрузить тестовые данные. Нужен Docker Desktop.
chcp 65001 >nul
cd /d "%~dp0"
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo Не удалось запустить. Проверьте, что Docker Desktop запущен.
  pause
  exit /b 1
)
echo Загружаю тестовые данные (первый раз - около минуты)...
docker compose logs -f seed
echo.
echo Готово: откройте http://localhost:8080
echo Вход: ivanova / sidorova (юрист), petrov (просмотр), любой другой логин - администратор. Пароль: dev
start http://localhost:8080
pause
