# Document Assistant

Сервис для автоматической обработки клиентских запросов по страхованию.

Клиент присылает документ (Excel, Word или PDF) с перечнем необходимых страховых случаев.
Сервис находит наиболее подходящую программу страхования из нормативной базы,
сравнивает её с требованиями клиента и возвращает ответ в формате клиента с комментариями «Есть / Нет / Частично».

---

## Архитектура

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
       ├── GeminiModel                 — запрос к LLM (Gemini; легко заменить)
       │
       ├── PostProcessor               — парсит ответ LLM → InsuranceReport
       │
       └── ReportExport                — сохраняет файл в формате клиента
               ├── ExcelReportWriter   — .xlsx / .xls
               └── WordReportWriter    — .docx / .doc (fallback для PDF)
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
| `DATABASE_URL` | Да | Строка подключения к БД |
| `GEMINI_API_KEY` | Да | API-ключ Google Gemini |
| `AI_MODEL_NAME` | Нет | Имя модели (по умолчанию `gemini-1.5-flash`) |
| `AI_TEMPERATURE` | Нет | Температура генерации (по умолчанию `0.2`) |
| `AI_ROLE` | Да | Системная роль модели |
| `AI_PROMPT_TEMPLATE` | Да | Шаблон промта с плейсхолдерами `{role}`, `{normative_base}`, `{examples}`, `{source_text}` |
| `TELEGRAM_BOT_TOKEN` | Нет | Токен Telegram-бота |

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
