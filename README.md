# Document Assistant

Сервис для автоматической обработки клиентских запросов по страхованию.

Клиент присылает документ (Excel, Word или PDF) с перечнем необходимых страховых случаев.
Сервис находит наиболее подходящую программу страхования из нормативной базы,
сравнивает её с требованиями клиента и возвращает ответ в формате клиента с комментариями «Есть / Нет / Частично».

---

## Архитектура

Диаграмма классов — [docs/class_diagram.md](docs/class_diagram.md)

```
POST /api/update
       │
       ▼
 AIAssistantService
       │
       ├── DocumentPreprocessor
       │       ├── DataParser          — читает файл клиента (Excel / Word / PDF) → markdown
       │       ├── TextEncoder         — нормализует текст перед отправкой в LLM
       │       ├── NormativeBaseLoader — загружает нормативную базу (файл или папка)
       │       ├── ExamplesLoader      — загружает примеры ответов из папки examples/
       │       └── PromptEngine        — собирает итоговый промт
       │
       ├── ModelFactory                — выбирает модель по AI_PROVIDER
       │       ├── GeminiModel         — облачная модель Google Gemini
       │       └── LocalLLMModel       — локальная модель через Ollama (HTTP)
       │
       ├── PostProcessor               — парсит ответ LLM → InsuranceReport
       │
       └── ReportExport                — сохраняет файл в формате клиента
               ├── ExcelReportWriter   — .xlsx / .xls
               └── WordReportWriter    — .docx / .doc (fallback для PDF)
```

---

## Работа с LLM

### Выбор модели

Модель выбирается через переменную `AI_PROVIDER` в `.env` — без изменений в коде.
При старте приложения `ModelFactory.create()` читает настройку и создаёт нужный объект:

```
AI_PROVIDER=gemini  →  GeminiModel    (Google Gemini API, облако)
AI_PROVIDER=local   →  LocalLLMModel  (Ollama, локальный Docker-контейнер)
```

Оба класса реализуют один интерфейс `AIModel.response(query: str) -> str`,
поэтому остальной код не знает, с какой моделью работает.

---

### Локальная модель (Ollama)

#### Как загружается модель

Загрузка происходит один раз при первом `docker compose up` через сервис `ollama-init`:

```
docker compose up
        │
        ├── ollama          — запускает HTTP-сервер на :11434
        │       └── healthcheck: GET /api/tags → 200 OK
        │
        ├── ollama-init     — ждёт healthy, затем:
        │       └── ollama pull qwen2.5:7b  (~4.7 ГБ, Q4_K_M квантизация)
        │               └── модель сохраняется в Docker volume ollama_data
        │
        └── api             — стартует только после ollama-init: completed
```

При повторных запусках `ollama pull` проверяет хэши и выходит мгновенно —
модель уже лежит в volume и не скачивается заново.

#### Как модель хранится в памяти

`OLLAMA_KEEP_ALIVE=24h` держит модель загруженной в RAM между запросами.
Без этого Ollama выгружает модель через 5 минут простоя, и следующий запрос
ждёт ~10–30 секунд холодного старта.

```
Первый запрос:   загрузка в RAM (~10–30 сек) + инференс
Следующие:       только инференс (модель уже в памяти)
```

Параметры экономии памяти (8 ГБ RAM):

| Переменная | Значение | Эффект |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | одна задача за раз, не делит RAM |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | не держит в памяти вторую модель |
| `memory limit` | `5500m` | защищает хост от OOM |

#### Как происходит запрос

`LocalLLMModel` отправляет синхронный HTTP POST в контейнер Ollama:

```
FastAPI (api:80)
    │
    │  POST http://ollama:11434/api/chat
    │  {
    │    "model": "qwen2.5:7b",
    │    "messages": [{"role": "user", "content": "<промт>"}],
    │    "stream": false,
    │    "options": {"temperature": 0.2}
    │  }
    │
ollama:11434
    │
    └── ответ: {"message": {"content": "<текст ответа>"}}
```

Таймаут запроса — 120 секунд (с запасом на CPU-инференс).
`stream: false` — ждём полный ответ, не стриминг, это проще для парсинга таблицы.

---

### Облачная модель (Gemini)

`GeminiModel` использует официальный SDK `google-genai`.
Переключение — только `AI_PROVIDER=gemini` в `.env`, ключ `GEMINI_API_KEY` обязателен.

---

### Добавление новой модели

Достаточно унаследоваться от `AIModel` и зарегистрировать в `ModelFactory`:

```python
class MyModel(AIModel):
    def response(self, query: str) -> str:
        ...

# в ModelFactory.create():
if settings.ai_provider == "my_provider":
    return MyModel(...)
```

---

## Быстрый старт

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Создать `.env`

```bash
cp .env.example .env
```

Заполнить все обязательные переменные (см. раздел [Конфигурация](#конфигурация)).

### 3. Запустить сервер

```bash
uvicorn main:app --reload
```

---

## API

### `POST /api/update`

Принимает путь к файлу клиента, запускает обработку, возвращает путь к результирующему файлу.

**Тело запроса:**

```json
{
  "request_id": 1,
  "file_path": "/data/requests/client_request.xlsx",
  "user_name": "Иванов И.И.",
  "priority": 0
}
```

**Ответ (200):**

```json
{
  "request_id": 1,
  "user_name": "Иванов И.И.",
  "output_file": "/data/requests/client_request_ответ.xlsx"
}
```

Выходной файл создаётся рядом с входным с суффиксом `_ответ`.

---

## Конфигурация

Все параметры задаются через `.env`. Пример — в [.env.example](.env.example).

| Переменная | Обязательная | Описание |
|---|---|---|
| `NORMATIVE_BASE` | Да | Путь к нормативной базе (файл или папка с документами) |
| `EXAMPLES_PATH` | Нет | Путь к папке с примерами (см. ниже) |
| `AI_PROVIDER` | Нет | `gemini` (по умолчанию) или `local` |
| `AI_TEMPERATURE` | Нет | Температура генерации (по умолчанию `0.2`) |
| `AI_ROLE` | Да | Системная роль модели |
| `AI_PROMPT_TEMPLATE` | Да | Шаблон промта с плейсхолдерами `{role}`, `{normative_base}`, `{examples}`, `{source_text}` |
| `GEMINI_API_KEY` | При `AI_PROVIDER=gemini` | API-ключ Google Gemini |
| `AI_MODEL_NAME` | Нет | Модель Gemini (по умолчанию `gemini-1.5-flash`) |
| `LLM_BASE_URL` | При `AI_PROVIDER=local` | Адрес Ollama (по умолчанию `http://ollama:11434`) |
| `LLM_MODEL_NAME` | При `AI_PROVIDER=local` | Модель Ollama (по умолчанию `qwen2.5:7b`) |

Многострочные значения в `.env` записываются в одну строку с `\n`:

```env
AI_PROMPT_TEMPLATE={role}\n\n## НОРМАТИВНАЯ БАЗА:\n{normative_base}\n\n...
```

---

## Поддерживаемые форматы

| Формат | Чтение | Запись |
|---|---|---|
| `.xlsx` / `.xls` | Да | Да |
| `.docx` / `.doc` | Да | Да |
| `.pdf` | Да | Fallback → `.docx` |

---

## Примеры (few-shot)

Для повышения качества ответов можно добавить примеры в папку `EXAMPLES_PATH`.

Структура:

```
examples/
  001/
    client.xlsx      # запрос клиента (любой поддерживаемый формат)
    response.docx    # ответ специалиста (любой поддерживаемый формат)
  002/
    ...
```

Каждая подпапка — один пример. В ней должно быть ровно два файла:
первый (по алфавиту) — запрос клиента, второй — ответ специалиста.

---

## Нормативная база

`NORMATIVE_BASE` может указывать на:

- **Файл** — `.txt`, `.md`, `.docx`, `.pdf`, `.xlsx`
- **Папку** — все поддерживаемые файлы в ней будут загружены и объединены

---

## Тесты

```bash
pytest tests/ -v
```

Тесты не требуют реальных файлов — все фикстуры создаются программно через `tmp_path`.

---

## Структура проекта

```
document_assistant/
  ai/
    encoders.py        — TextEncoder
    model.py           — AIModel, GeminiModel
    postprocessor.py   — PostProcessor (парсинг ответа LLM)
    preprocessor.py    — DocumentPreprocessor, ExamplesLoader, ProcessingTask
    promt_builders.py  — PromptEngine, NormativeBaseLoader
  core/
    parsers.py         — DataParser, Excel, Word, PDF, MarkdownTableBuilder
    pydantic_models.py — схема входящего запроса
    settings.py        — Settings (pydantic-settings)
  reports/
    report_models.py   — InsuranceReport, ReportRow
    report_export.py   — ReportExport
    writers.py         — ExcelReportWriter, WordReportWriter
  services/
    assistant.py       — AIAssistantService (оркестратор)
main.py                — FastAPI приложение
tests/                 — pytest-тесты
```
