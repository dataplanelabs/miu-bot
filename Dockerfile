# Build stage
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml .
COPY miu_bot/ miu_bot/
COPY bridge/ bridge/
RUN pip install --no-cache-dir ".[postgres,temporal,otel,pdf]"

# Runtime stage
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/miubot /usr/local/bin/miubot
COPY miu_bot/ miu_bot/
COPY alembic.ini .

EXPOSE 18790

ENTRYPOINT ["miubot"]
CMD ["serve"]
