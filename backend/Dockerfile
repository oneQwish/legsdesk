FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY fields.toml settings.toml penalty.toml ./
COPY migrations ./migrations
COPY forms ./forms
RUN useradd -r -u 1000 lawdesk && mkdir -p /data/storage && chown lawdesk /data/storage /app/forms
USER lawdesk
ENV LAWDESK_STORAGE_DIR=/data/storage
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
