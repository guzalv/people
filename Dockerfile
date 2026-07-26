FROM python:3.12-slim

WORKDIR /app

# gosu: entrypoint starts as root to fix bind-mount ownership, then drops to
# appuser for the actual process.
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/
COPY docker-entrypoint.sh /usr/local/bin/

RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data && chown appuser:appuser /data \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PEOPLE_DB=/data/people.db
EXPOSE 8080
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
