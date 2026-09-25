#!/usr/bin/env bash
# Генерирует k8s/generated/configmap.env и k8s/generated/secret.env из .env
# в корне репозитория. Значения секретных ключей нигде не печатаются в консоль.
set -euo pipefail

cd "$(dirname "$0")/.."

SECRET_KEYS="DATABASE_URL SESSION_SECRET KEYCLOAK_CLIENT_SECRET GEMINI_API_KEY ANTHROPIC_API_KEY VSK_API_KEY"

mkdir -p k8s/generated
: > k8s/generated/configmap.env
: > k8s/generated/secret.env

while IFS= read -r line; do
  [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
  key="${line%%=*}"
  is_secret=false
  for sk in $SECRET_KEYS; do
    [[ "$key" == "$sk" ]] && is_secret=true && break
  done
  if $is_secret; then
    echo "$line" >> k8s/generated/secret.env
  else
    echo "$line" >> k8s/generated/configmap.env
  fi
done < .env

# K8s-специфичные переопределения
sed -i '/^STORAGE_DIR=/d' k8s/generated/configmap.env
echo "STORAGE_DIR=/data" >> k8s/generated/configmap.env

sed -i '/^AUTH_DISABLED=/d' k8s/generated/configmap.env
echo "AUTH_DISABLED=true" >> k8s/generated/configmap.env  # этап 1: Keycloak отключён

# Значение из .env имеет приоритет; если его там нет — ставим явно, чтобы
# DevOps видел ключ в ConfigMap и мог поднять детализацию без пересборки.
if ! grep -q '^LOG_LEVEL=' k8s/generated/configmap.env; then
  echo "LOG_LEVEL=INFO" >> k8s/generated/configmap.env
fi

if ! grep -q '^DATABASE_URL=' k8s/generated/secret.env 2>/dev/null; then
  echo "DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>" >> k8s/generated/secret.env
fi

echo "Готово: k8s/generated/configmap.env, k8s/generated/secret.env"
echo "ВАЖНО: заполните в secret.env реальный DATABASE_URL внешнего Postgres."
if grep -q '^SESSION_SECRET=dev-insecure-session-secret$' k8s/generated/secret.env 2>/dev/null; then
  echo "ВНИМАНИЕ: SESSION_SECRET = дефолтное небезопасное значение — замените перед деплоем в контур."
fi
