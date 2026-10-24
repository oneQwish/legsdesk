# Пилот «всё в одном»: интерфейс + сервер + генератор данных в одном образе. Сборка из корня репозитория:
#   docker compose -f pilot/docker-compose.yml up -d --build
FROM node:22-alpine AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /srv/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/fields.toml backend/settings.toml ./
COPY backend/migrations ./migrations
COPY connectors /srv/connectors
COPY --from=web /src/dist /srv/frontend/dist
ENV LAWDESK_FRONTEND_DIST=/srv/frontend/dist LAWDESK_STORAGE_DIR=/data/storage TZ=Europe/Moscow PYTHONUNBUFFERED=1
RUN useradd -r -u 1000 lawdesk && mkdir -p /data/storage && chown lawdesk /data/storage
USER lawdesk
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
