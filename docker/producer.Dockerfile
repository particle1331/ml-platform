FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "celery[redis]==5.6.3" \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.34,<1" \
    "flet[web]==1.0.3" \
    "httpx>=0.27,<1"

COPY src ./src

ENV PYTHONPATH=/app/src

CMD ["uvicorn", "ml_platform.producer:app", "--host=0.0.0.0", "--port=8000"]
