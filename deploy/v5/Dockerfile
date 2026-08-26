FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
ENV V5_SERVICE_ID=orchestrator
ENV V5_SERVICE_PORT=8100
CMD ["sh", "-c", "uvicorn src.v5.service_host:app --host 0.0.0.0 --port ${V5_SERVICE_PORT}"]
