#!/bin/sh
# Пилот рабочего места юриста: собрать, запустить, загрузить тестовые данные. Нужен Docker.
cd "$(dirname "$0")" || exit 1
docker compose up -d --build || { echo "Не удалось запустить. Проверьте, что Docker запущен."; exit 1; }
echo "Загружаю тестовые данные (первый раз — около минуты)…"
docker compose logs -f seed
echo
echo "Готово: http://localhost:8080"
echo "Вход: ivanova / sidorova (юрист), petrov (просмотр), любой другой логин — администратор. Пароль: dev"
