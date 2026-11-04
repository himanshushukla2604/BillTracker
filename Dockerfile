# One image: build the React app, then run FastAPI, which serves both the API and the app.

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FT_DB=/data/finance.db \
    FT_BACKUP_DIR=/data/backups \
    FT_SEED=0
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=web /web/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8080
# --proxy-headers: the host terminates HTTPS, so trust its X-Forwarded-Proto and mark the login cookie Secure.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
