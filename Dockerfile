FROM python:3.11-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system --gid 10001 status \
    && useradd --system --uid 10001 --gid status --home-dir /app --no-create-home status \
    && mkdir -p /app/data \
    && chown status:status /app/data

COPY --chown=status:status app/ .

USER status

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
