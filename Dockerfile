FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY frontend ./frontend

# Hosts like Render inject PORT; default to 8000 for local docker-compose.
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os, urllib.request as u; u.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/health', timeout=3)"

# --proxy-headers makes the rate limiter see the real client IP behind a load balancer.
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'
