FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPSWATCH_DATA_DIR=/data \
    OPSWATCH_HOST=0.0.0.0 \
    OPSWATCH_PORT=8765

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client default-mysql-client tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY opswatch ./opswatch
RUN pip install --no-cache-dir ".[s3]"

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health').status == 200 else 1)"

CMD ["opswatch", "run"]
