FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV FPL_TEAM_ID=3462711
ENV FPL_LIVE_POLL_SECONDS=60
CMD ["uvicorn","live_service:app","--host","0.0.0.0","--port","8000"]
