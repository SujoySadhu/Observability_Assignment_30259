FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY orderapi ./orderapi

# Run as an unprivileged user, not root.
RUN useradd --system --uid 10001 appuser
USER appuser

EXPOSE 8000

# Liveness check used by `docker compose ps` (healthy / unhealthy).
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# ONE worker process on purpose: prometheus_client keeps metrics in process
# memory. With several workers, each scrape would hit a random worker and see
# only that worker's counters. (Scale with more containers instead.)
CMD ["uvicorn", "orderapi.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
