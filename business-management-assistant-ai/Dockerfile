FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY static ./static
COPY docs ./docs
COPY scripts/docker-entrypoint.sh ./docker-entrypoint.sh
RUN pip install --no-cache-dir ".[postgres]" \
 && chmod +x docker-entrypoint.sh \
 && useradd --system --uid 10001 --no-create-home assistant \
 && mkdir -p /service/models /service/data/evaluation && chown -R assistant /service/models /service/data
USER assistant
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).status == 200 else 1)"
# Behind a reverse proxy set UVICORN_ARGS="--proxy-headers --forwarded-allow-ips <proxy ip>"
CMD ["./docker-entrypoint.sh"]
