FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 80

# worker переопределяет команду в docker-compose.yaml (python -m document_assistant.worker) —
# этот CMD используется только сервисом api. MAX_WORKERS/TIMEOUT раньше были magic-переменными
# gunicorn_conf.py из образа tiangolo/uvicorn-gunicorn-fastapi — теперь их нет, задаём явно.
# --forwarded-allow-ips: доверять X-Forwarded-Proto от Ingress, иначе за TLS-терминацией
# redirect_uri для Keycloak строится как http:// и Keycloak его отвергает.
CMD ["gunicorn", "main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:80", \
     "--workers", "2", \
     "--timeout", "120", \
     "--forwarded-allow-ips", "*"]
