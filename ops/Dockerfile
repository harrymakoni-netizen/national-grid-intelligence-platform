FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini .
COPY data/processed/ data/processed/

ENV PYTHONPATH=/app/src

CMD ["uvicorn", "gridintel.ingestion.api:app", "--host", "0.0.0.0", "--port", "8000"]
