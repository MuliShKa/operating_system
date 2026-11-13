FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/os2-venv

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN /opt/os2-venv/bin/pip install --no-cache-dir -r requirements.txt
COPY config ./config
COPY sql ./sql
COPY sources ./sources
COPY src ./src

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin os2 \
    && mkdir -p /app/data /tmp/songdo-os2 \
    && chown -R os2:os2 /app/data /tmp/songdo-os2

ENV PATH="/opt/os2-venv/bin:${PATH}" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=2)" || exit 1

CMD ["python", "-m", "edge.supervisor"]
