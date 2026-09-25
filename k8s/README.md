# Kubernetes-манифесты — ДМС-ассистент (этап 1, без Keycloak)

Один образ (`ghcr.io/justsuvorov/document-assistant:0.1`) на оба Deployment'а —
`api` и `worker` отличаются только командой запуска контейнера, как и в
`docker-compose.yaml`.

## Перед apply

1. **Образ должен быть запушен**: `docker push ghcr.io/justsuvorov/document-assistant:0.1`.

2. **Image pull secret** (репозиторий приватный) — создать самостоятельно, с PAT:
   ```bash
   kubectl create namespace document-assistant
   kubectl create secret docker-registry ghcr-pull-secret \
     --docker-server=ghcr.io \
     --docker-username=<ваш GitHub username> \
     --docker-password=<PAT с write:packages> \
     -n document-assistant
   ```

3. **ConfigMap и Secret** уже сгенерированы в `k8s/generated/` скриптом
   `render-config.sh` (см. ниже) из корневого `.env`. Проверьте перед apply:
   - `k8s/generated/configmap.yaml` — можно открыть и посмотреть, значения не секретные.
   - `k8s/generated/secret.yaml` — **не открывайте в чате/скриншотах**, это реальные значения в base64 (не шифрование, тривиально декодируется).

4. **`DATABASE_URL` в secret.yaml — плейсхолдер**, его нет в текущем `.env`
   (там указан внешний Postgres по договорённости). Замените на реальный:
   ```
   postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
   ```
   Проще всего — поправить `k8s/generated/secret.env` (если ещё не удалён) и
   перегенерировать, либо руками отредактировать base64-значение в
   `secret.yaml` через `echo -n '...' | base64`.

5. **`AUTH_DISABLED=true`** уже выставлен в `configmap.yaml` скриптом —
   это этап 1 (Keycloak отключён), как договаривались. Значит **все
   пользователи контура делят одну сессию** (`dev-user`) — учтите при приёмке.
   Когда будете подключать Keycloak — поменяйте на `false` и заполните
   `KEYCLOAK_URL`/`KEYCLOAK_REALM`/`KEYCLOAK_CLIENT_ID` в ConfigMap и
   `KEYCLOAK_CLIENT_SECRET` в Secret.

6. **`STORAGE_DIR=/data`** — тоже выставлен скриптом принудительно, должен
   совпадать с `mountPath` в `pvc.yaml`/Deployment'ах (уже совпадает).

## Пересоздать ConfigMap/Secret из актуального `.env`

```bash
bash k8s/render-config.sh
kubectl create configmap document-assistant-config \
  --from-env-file=k8s/generated/configmap.env -n document-assistant \
  --dry-run=client -o yaml > k8s/generated/configmap.yaml
kubectl create secret generic document-assistant-secret \
  --from-env-file=k8s/generated/secret.env -n document-assistant \
  --dry-run=client -o yaml > k8s/generated/secret.yaml
rm k8s/generated/configmap.env k8s/generated/secret.env   # не оставлять plaintext секреты на диске
```

## Заполнить перед apply

- `pvc.yaml` — `storageClassName` (ваш RWX storage class)
- `ingress.yaml` — `ingressClassName`, `host`

## Apply (по порядку)

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/generated/configmap.yaml
kubectl apply -f k8s/generated/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/deployment-api.yaml
kubectl apply -f k8s/deployment-worker.yaml
kubectl apply -f k8s/service-api.yaml
kubectl apply -f k8s/ingress.yaml
```

## Проверка

```bash
kubectl -n document-assistant get pods
kubectl -n document-assistant logs deploy/document-assistant-api
kubectl -n document-assistant logs deploy/document-assistant-worker
kubectl -n document-assistant port-forward svc/document-assistant-api 8080:80
curl http://localhost:8080/healthz
```

## Известные ограничения этапа 1

- `AUTH_DISABLED=true` → нет реальной multi-tenant изоляции, все видят сессии
  друг друга (см. п.5 выше) — ожидаемо, не баг.
- `k8s/generated/` — в `.gitignore`, туда не должны попасть реальные секреты
  в git. Проверяйте `git status` перед коммитом чего-либо из `k8s/`.
