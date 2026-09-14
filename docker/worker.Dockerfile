FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir "celery[redis]==5.6.3"

COPY src ./src

ENV PYTHONPATH=/app/src

CMD ["celery", "-A", "ml_platform.celery_app", "worker", "--loglevel=INFO", "--events", "--concurrency=1"]
