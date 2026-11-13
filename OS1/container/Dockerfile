# OCI image for the OS1 edge node. Build from the OS1 folder:
#   docker build -f container/Dockerfile -t songdo-edge-os1 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    EDGE_DATABASE_PATH=/app/data/songdo.db \
    EDGE_API_HOST=0.0.0.0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config ./config
COPY sql ./sql
COPY src ./src
COPY scripts ./scripts
COPY sources ./sources

# Run as an unprivileged user; the database lives in a volume.
RUN useradd --create-home --uid 10001 edge \
    && mkdir -p /app/data \
    && chown -R edge:edge /app/data
USER edge
VOLUME ["/app/data"]

EXPOSE 8000

# Healthy only if the API answers and every worker reports running.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import json,sys,urllib.request; s=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=2)); w=s['workers']; sys.exit(0 if w and all(v['status']=='running' for v in w.values()) else 1)"]

# The supervisor traps SIGTERM, stops and joins every worker (no zombies).
STOPSIGNAL SIGTERM
CMD ["python", "-m", "edge.supervisor"]
