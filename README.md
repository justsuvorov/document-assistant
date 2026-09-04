# Document Assistant — Qwen Release (GUI + API)

Интегрированное решение с двумя независимыми пайплайнами сверки документов на базе LLM:
1. **ДМС** — сверка клиентского запроса с нормативной базой программ страхования (`POST /api/update`, статусы Есть/Нет/Частично).
2. **Сверка деклараций с ген. полисом (cargo)** — сверка деклараций на перевозку груза с генеральным полисом и ДС к нему (`POST /api/reconcile`, статусы Совпадает/Не совпадает/Не знаю). Подробности бизнес-логики — в `BUSINESS.md`.

Включает:
- **REST API** (FastAPI) для автоматизации обработки документов
- **Desktop GUI** (PyEdifice + PySide6) с переключателем режимов ДМС / Сверка грузов
- **Подключение к Qwen** через OpenAI-compatible API
- **Retry-логика** при ошибках сервиса
- **Частичные результаты** при обработке больших документов
- **Логирование** во все медиа (консоль + файл)

---

## Быстрый старт

### Вариант 1: Desktop приложение (EXE)

Скачай готовый EXE из `dist/` и настрой подключение:

```json
// app/config.json
{
  "api_base_url": "http://your-server.com:8001"
}
```

Запусти: `ВСК ДМС-ассистент.exe`

**Что происходит:**
- Все действия логируются в `app.log` рядом с EXE
- При обработке больших документов (100+ чанков) каждый чанк повторяется до 3 раз при ошибке
- Результат сохраняется даже если часть чанков упала

### Вариант 2: Docker контейнер (API только)

```bash
docker compose up -d
```

API доступен на `http://localhost:8001`

Используй GUI приложение для подключения или интегрируй в свой код:

```bash
curl -X POST http://localhost:8001/api/update \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": 1,
    "file_path": "/app/uploads/client.xlsx",
    "user_name": "Иванов И.И."
  }'
```

---

## Компоненты

| Компонент | Описание | Запуск |
|---|---|---|
| **app/main.py** | Desktop GUI приложение (вкладки «ДМС» / «Сверка грузов») | `ВСК ДМС-ассистент.exe` или `python app/main.py` |
| **main.py** | FastAPI REST API | `docker compose up` или `uvicorn main:app` |
| **QWEN API** | LLM модель | Подключение через QWEN_API_URL |

---

## Архитектура обработки документов

```
Клиентский документ (.xlsx / .docx / .pdf)
       ↓ DataParser
Сырой текст
       ↓ TextEncoder (обрезка до 2,200,000 символов)
Нормализованный текст
       ↓ DocumentChunker (батчинг по LLM_BATCH_SIZE=25)
[chunk1, chunk2, ..., chunkN]  (обычно 3-50 чанков)
       ↓ для каждого чанка: PromptEngine.build()
Промты с нормативной базой (RAG через ContextBuilder)
       ↓ QwenModel.response() с retry (макс 3 попытки)
           ├─ Успех → сохранить результат
           ├─ Ошибка 504/503 → повтор через 5 сек
           └─ После 3 попыток → пропустить, перейти к следующему
Результаты по всем чанкам (даже если некоторые упали)
       ↓ InsuranceReport.merge()
Итоговый отчёт
       ↓ ReportExport
client_ответ.xlsx или client_ответ.docx
```

---

## Конфигурация

### Desktop приложение (app/config.json)

```json
{
  "api_base_url": "http://your-server.com:8001"
}
```

Логирование: `app.log` рядом с EXE

### API сервис (.env)

```bash
# Обязательные
NORMATIVE_BASE=/app/normative_base
AI_ROLE="Ты — опытный специалист..."
AI_PROMPT_TEMPLATE="{role}\n\n..."

# Qwen модель
QWEN_API_URL=https://model-1.ai-api.vsk.ru/v1/completions
QWEN_MODEL_NAME=Qwen3.6-35B-A3B-NVFP4
QWEN_MAX_TOKENS=100000
QWEN_NUM_CTX=400000

# Обработка
LLM_MAX_CHARS=2200000
LLM_MAX_SECTIONS=300       # макс разделов нормативной базы
LLM_MAX_CHUNKS=0           # 0 = все
LLM_BATCH_SIZE=25          # размер батча при разбивке
AI_TEMPERATURE=0.2

# Сверка деклараций с ген. полисом (cargo, /api/reconcile) — опционально
RECONCILIATION_RULES_BASE=/app/cargo_normative_base
SPECIAL_CONDITIONS_GLOBAL_PATH=
RECONCILIATION_TEMPLATE_HORIZONTAL=   # форма ответа ПСГ (мультистрочные), пусто = встроенная
RECONCILIATION_TEMPLATE_VERTICAL=     # форма ответа вертикальная (однострочные), пусто = встроенная
DECLARATIONS_MONTH_FORMAT=%Y-%m
MATRIX_AI_ROLE="Ты — специалист по анализу..."
MATRIX_PROMPT_TEMPLATE="{role}\n\n..."
RECONCILIATION_AI_ROLE="Ты — специалист по сверке..."
RECONCILIATION_PROMPT_TEMPLATE="{role}\n\n..."
```

---

## Retry-логика и обработка ошибок

### При обработке каждого чанка:

1. **Попытка 1-3:** Вызвать LLM
2. **При ошибке 504/503/timeout:** Пауза 5 сек, повтор
3. **После 3 попыток:**
   - Ошибка логируется
   - Чанк помечается как пропущенный
   - Переход к следующему чанку
4. **В конце:** Сохранить все обработанные результаты

**Пример лога при ошибке:**
```
2026-07-13 14:23:45 | WARN  | Чанк 55: ошибка на попытке 1/3: 504 Service Unavailable
2026-07-13 14:23:50 | WARN  | Чанк 55: ошибка на попытке 2/3: 504 Service Unavailable
2026-07-13 14:23:55 | ERROR | Чанк 55 пропущен после 3 попыток
```

Результат будет сохранён с тем что удалось обработать (чанки 1-54, 56-120 будут в ответе).

---

## API эндпоинты

### POST /api/update

Запустить обработку файла.

```json
{
  "request_id": 1,
  "file_path": "/app/uploads/client.xlsx",
  "user_name": "Иванов И.И.",
  "max_chunks": 0
}
```

**Ответ (200):**
```json
{
  "request_id": 1,
  "output_file": "/app/uploads/client_ответ.xlsx"
}
```

### POST /api/estimate

Оценить объём без вызова LLM.

```json
{
  "file_path": "/app/uploads/client.xlsx"
}
```

**Ответ:**
```json
{
  "chunk_count": 45,
  "estimated_seconds": 5400,
  "total_chars": 1200000,
  "processed_chars": 1200000
}
```

### POST /api/rebuild

Пересобрать Excel из кэша LLM JSON.

```json
{
  "request_id": 1,
  "json_path": "/app/uploads/client_llm_output.json",
  "file_path": "/app/uploads/client.xlsx",
  "user_name": "Иванов И.И."
}
```

### POST /api/reconcile

Сверка деклараций с генеральным полисом и ДС (второй, независимый пайплайн — см. `BUSINESS.md`).

Ожидаемая структура `policy_folder`:
```
{policy_folder}/
├── ГП страхования грузов.docx     — ген.полис (имя файла начинается с "ГП")
├── ДС/                             — подпапка со всеми ДС
│   ├── ДС 1 (п.9).docx             — номер ДС + номера изменяемых пунктов в имени файла
│   ├── ДС 2 (п.5).docx
│   └── ДС 3 (п.9, п. 7).docx
└── Декларации/                     — декларации по умолчанию (можно переопределить)
    └── 2026-08/
        └── 200.xlsx
```

Минимальный запрос (всё по умолчанию — автопоиск ген.полиса, папки ДС и деклараций):
```json
{
  "request_id": 1,
  "policy_folder": "//server/share/Клиент/Ген.полис"
}
```

Запрос с явными путями и override, если реальная структура клиента отличается от стандартной:
```json
{
  "request_id": 1,
  "policy_folder": "//server/share/Клиент/Ген.полис",
  "policy_file_override": null,
  "ds_folder_override": null,
  "declaration_paths": [
    "//server/share/Клиент/Декларации/2026-08/200.xlsx"
  ],
  "special_conditions_path": null,
  "force_rebuild_matrix": false
}
```

`declaration_paths` — необязательное поле; каждый элемент может быть путём к файлу ИЛИ к папке (папка сканируется рекурсивно). Если поле не передано вовсе, декларации ищутся в `{policy_folder}/Декларации/` (рекурсивно, включая помесячные подпапки).

**Ответ (200):**
```json
{
  "request_id": 1,
  "policy_folder": "//server/share/Клиент/Ген.полис",
  "matrix": { "clause_count": 42, "fingerprint": "...", "cache_hit": true },
  "declarations": [
    {
      "declaration_path": "//server/share/Клиент/Декларации/2026-08/200.xlsx",
      "declaration_number": "200",
      "type": "single",
      "line_items": 1,
      "row_count": 6,
      "output_file": "//server/share/Клиент/Декларации/2026-08/200 – результат проверки.xlsx",
      "warnings": []
    }
  ]
}
```

Матрица актуальных правил (генеральный полис + все ДС) кэшируется рядом с папкой полиса (`_matrix_cache.json`) и пересчитывается только при изменении состава файлов, либо принудительно через `force_rebuild_matrix: true`. По каждому номеру пункта побеждает текст из ДС с наибольшим номером, который его затрагивал.

---

## Файлы результатов

После обработки сохраняются:

- **client_ответ.xlsx** — итоговый отчёт с аннотациями
- **client_llm_output.json** — кэш LLM ответов (для rebuild)
- **client_llm_debug.md** — сырые LLM ответы по чанкам

### Структура JSON кэша:

```json
{
  "file_path": "/app/uploads/client.xlsx",
  "processed_at": "2026-07-13T14:23:00+00:00",
  "model": "Qwen3.6-35B-A3B-NVFP4",
  "provider": "qwen",
  "chunks": [
    {
      "index": 1,
      "raw_response": "...",
      "rows_parsed": 25
    },
    {
      "index": 55,
      "raw_response": "",
      "rows_parsed": 0,
      "error": "504 Service Unavailable"
    }
  ]
}
```

---

## Логирование

### Desktop приложение (EXE)

Все логи пишутся в **`app.log`** рядом с EXE.

Пример:
```
2026-07-13 14:23:45 | INFO  | Приложение запущено
2026-07-13 14:25:10 | INFO  | Загруженный файл: client.xlsx (2MB)
2026-07-13 14:25:15 | INFO  | Обработка 45 чанков
2026-07-13 14:25:20 | INFO  | Чанк 1/45...
2026-07-13 14:25:25 | WARN  | Чанк 55: ошибка на попытке 1/3: 504 Service Unavailable
2026-07-13 14:25:30 | WARN  | Чанк 55: ошибка на попытке 2/3: 504 Service Unavailable
2026-07-13 14:25:35 | ERROR | Чанк 55 пропущен после 3 попыток
2026-07-13 14:30:00 | INFO  | Готово: client_ответ.xlsx
```

### API (Docker)

Логи выводятся в консоль контейнера:

```bash
docker logs -f document_assistant
```

---

## Поддерживаемые форматы

| Формат | Чтение | Запись | Примечание |
|---|---|---|---|
| `.xlsx` / `.xls` | ✅ | ✅ | Аннотирование на месте (+ 3 столбца) |
| `.docx` / `.doc` | ✅ | ✅ | Новый документ с таблицей |
| `.pdf` | ✅ | ❌ | Только текстовый (не сканы), fallback на .docx |

---

## Структура проекта

```
document_assistant/     — API сервис
├── ai/
│   ├── model.py              — QwenModel с retry-логикой
│   ├── preprocessor.py       — DocumentChunker (батчинг)
│   ├── postprocessor.py      — Парсинг LLM ответов
│   ├── promt_builders.py     — PromptEngine, RAG
│   ├── context_builder.py    — Управление контекстом
│   └── encoders.py           — TextEncoder
├── core/
│   ├── settings.py           — Конфигурация (.env)
│   ├── parsers.py            — Парсеры (Excel, Word, PDF)
│   └── pydantic_models.py    — Модели API запросов
├── reports/
│   ├── writers.py            — ExcelReportWriter (4-уровневый matching)
│   ├── style.py               — общая цветовая палитра (ДМС + cargo)
│   ├── report_export.py      — ReportExport
│   └── report_models.py      — InsuranceReport, ReportRow
├── services/
│   └── assistant.py          — AIAssistantService (единый оркестратор: retry,
│                                чанк-цикл, merge, export — используется и ДМС-,
│                                и cargo-пайплайном, см. ниже)
└── cargo/                — сверка деклараций с ген. полисом (/api/reconcile)
    ├── filename_parsing.py       — разбор имён файлов (полис/ДС/декларация)
    ├── policy_discovery.py       — PolicyFolderScanner
    ├── rules_matrix_builder.py   — по каждому источнику вызывает AIAssistantService,
    │                                затем ClauseMerger сводит кандидатов в матрицу
    ├── clause_merger.py          — "последний ДС побеждает" (чистая функция)
    ├── rules_matrix_cache.py     — кэш матрицы по папке полиса
    ├── rules_matrix_service.py   — get_or_build с кэшированием
    ├── preprocessors.py          — DeclarationPreprocessor, ClauseExtractionPreprocessor
    │                                (наследуют Preprocessor из ai/preprocessor.py)
    ├── declaration_classifier.py — одна перевозка / мультистрочная (без ИИ)
    ├── declaration_numbering.py  — "200" / "200/1" / имя файла результата
    ├── special_conditions.py     — общие + клиентские особые условия
    ├── reconciliation_prompt.py, reconciliation_postprocessor.py
    ├── reconciliation_writer.py  — ReconciliationExcelWriter(ReportWriter) —
    │                                вторая реализация ABC из reports/writers.py
    ├── report_export.py          — CargoReportExport, CandidateReportExport
    │                                (report_export для AIAssistantService)
    ├── output_paths.py           — путь результата, проверка месячной папки
    └── templates/
        └── reconciliation_form.xlsx  — фиксированная форма результата

Отдельного класса-оркестратора для сверки деклараций нет — main.py строит
AIAssistantService напрямую по одному экземпляру на файл декларации, через
_build_reconciliation_service() (см. main.py), точно так же, как
_build_service() строит его для /api/update.

app/                    — Desktop GUI
├── main.py                   — Edifice + PySide6
├── config.json               — Конфигурация (api_base_url)
├── config.json.example       — Пример конфига
├── requirements.txt          — Зависимости (edifice, PySide6, loguru)
└── assets/
    └── vsk_logo.png          — Логотип

build.spec              — Конфигурация PyInstaller
docker-compose.yaml     — Docker Compose (API + Qwen connection)
.env                    — Переменные окружения для Docker
.env.example            — Пример .env
requirements.txt        — API зависимости
main.py                 — FastAPI приложение
tests/                  — Модульные тесты
```

---

## Сборка EXE

```bash
# Установи зависимости GUI
pip install -r app/requirements.txt

# Собери EXE
pyinstaller build.spec --clean --noconfirm

# Готовый EXE в dist/ВСК ДМС-ассистент.exe
```

Рядом с EXE автоматически создаётся `app.log` для логирования.

---

## Производительность

| Сценарий | Время | Примечание |
|---|---|---|
| Малый документ (10 строк, 1 чанк) | ~30 сек | Зависит от Qwen API |
| Средний документ (100 строк, 5 чанков) | ~2-3 мин | С retry паузами |
| Большой документ (300+ строк, 50+ чанков) | ~10-20 мин | Может быть timeout на 504 |

При ошибке 504 на 50м-70м чанке приложение:
- Повторит 2 дополнительные попытки
- Если не помогло, пропустит чанк и продолжит
- В конце сохранит результат со всеми успешными чанками

---

## Корпоративный прокси

Настройки прокси лежат в одном файле `proxy.env` (в git не попадает — может содержать логин/пароль). Его читают и сборка, и запуск:

```bash
copy proxy.env.example proxy.env
# заполнить адрес прокси, затем как обычно:
build-all.bat
run-all.bat
```

Кода менять не нужно: `httpx` (вызовы LLM) и `requests` (GUI → API) читают переменные окружения сами.

**Главное, что нужно указать правильно — `NO_PROXY`.** Через прокси НЕ должны идти:
- `127.0.0.1, localhost` — GUI обращается к API локально; если этот трафик уйдёт на прокси, запрос не вернётся. `load-proxy.bat` добавляет их принудительно, даже если в `proxy.env` забыли;
- внутренние адреса LLM (`.vsk.ru`) — они доступны напрямую.

Проверить фактическую маршрутизацию:

```bash
python -c "import requests; print(requests.utils.get_environ_proxies('https://llm.ai-api.vsk.ru/x') or 'ПРЯМОЕ')"
```

**Если pip падает на SSL** (`CERTIFICATE_VERIFY_FAILED`) — прокси подменяет сертификаты. В `proxy.env` укажите корпоративный корневой сертификат (`PIP_CERT`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`) либо, как крайнюю меру, `PIP_TRUSTED_HOST`. Если у вас уже есть готовый `pip.ini` — достаточно прописать `PIP_CONFIG_FILE`.

---

## Решение проблем

### Ошибка "Not Found: ModuleNotFoundError: No module named 'PySide6'"

```bash
pip install PySide6 --upgrade
pip install -r app/requirements.txt
```

### Ошибка "504 Service Unavailable" постоянно

Это может быть перегрузка сервиса Qwen. Приложение автоматически повторит до 3 раз. Если продолжается:
- Проверь QWEN_API_URL
- Дождись когда разгрузится сервис
- Пересчитай документ

Частичные результаты всё равно будут сохранены.

### Где логи приложения?

- **Desktop EXE:** `app.log` рядом с файлом
- **Docker API:** `docker logs document_assistant`

---

## Дальнейшие улучшения

- [ ] Асинхронная обработка чанков (параллельные запросы)
- [ ] Queue система для массовой обработки
- [ ] Web интерфейс вместо GUI
- [ ] Поддержка более узких RAG стратегий
- [ ] Метрики обработки (в Prometheus/Grafana)
- [ ] Мониторинг здоровья Qwen API
- [ ] cargo: обкатать формат имён файлов ("ГП ...", "ДС N (п.X)") на полном объёме реальных файлов заказчика (см. `CONSTRAINTS.md`)
- [ ] cargo: извлечение даты начала периода страхования из декларации — для проверки месячной папки «Декларации/{месяц}»
- [ ] cargo: собрать `tests/cargo/test_cargo_real_files.py` на реальных файлах, когда они появятся
