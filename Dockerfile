FROM python:3.12-slim

# System deps for psycopg binary (libpq) — usually already in slim, but be explicit
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir --pre \
        agent-framework-core==1.0.0rc6 \
        agent-framework-foundry==1.0.0rc6

# Copy application code
COPY src/ ./src/
COPY terraform_templates/ ./terraform_templates/

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    SNOWIAC_DB_PATH=/data/snowiac.db

EXPOSE 8080

# Container Apps sets the PORT env var; use it.
CMD ["sh", "-c", "uvicorn snowiac.server:app --host 0.0.0.0 --port ${PORT}"]
