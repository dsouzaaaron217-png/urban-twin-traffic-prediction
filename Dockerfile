FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENABLE_TOMTOM_SCHEDULER=false \
    ENABLE_MODEL_RETRAINING=false \
    DATABASE_URL=sqlite:////var/lib/trafficwatch/trafficwatch.sqlite3

WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir -r requirements.lock
COPY . .
RUN mkdir -p /var/lib/trafficwatch \
    && useradd --create-home --uid 10001 trafficwatch \
    && chown -R trafficwatch:trafficwatch /app /var/lib/trafficwatch

USER trafficwatch
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
