# Document Assistant

Сервис для автоматической обработки клиентских запросов по страхованию.

Клиент присылает документ (Excel или Word) с перечнем необходимых страховых услуг.
Сервис сопоставляет их с нормативной базой страховых программ, анализирует каждое требование
и возвращает структурированный ответ с отметками «Есть / Нет / Частично».

---

## Архитектура

```
POST /api/update
       │
       ▼
 AIAssistantService
       │
       ├── DocumentPreprocessor
       │       ├── DataParser          — читает файл клиента (.xlsx / .docx) → текст
       │       ├── TextEncoder         — нормализует текст
       │       ├── DocumentChunker     — разбивает документ на разделы (^\\d+\\.\\s)
       │       └── PromptEngine        — собирает промт для каждого чанка
       │               └── ContextBuilder  — подбирает нормативную базу под контекст
       │                       └── NormativeIndex — Jaccard-поиск по 144 разделам
       │
       ├── ModelFactory                — выбирает модель по AI_PROVIDER
       │       ├── OllamaModel         — локальный CPU или удалённый GPU-сервер
       │       ├── GeminiModel         — Google Gemini API (облако)
       │       └── AnthropicModel      — Anthropic Claude API (облако)
       │
       ├── PostProcessor               — парсит ответ LLM → InsuranceReport
       │       └── InsuranceReport.merge() — объединяет ответы по всем чанкам
       │
       └── ReportExport                — сохраняет результат в формате клиента
               ├── ExcelReportWriter   — .xlsx
               └── WordReportWriter    — .docx
```

---

## Поток данных

```
client.xlsx / client.docx
       ↓  DataParser
Сырой текст
       ↓  TextEncoder
Нормализованный текст
       ↓  DocumentChunker  (разбивка по пронумерованным разделам)
[chunk1, chunk2, ..., chunkN]
       ↓  для каждого чанка: PromptEngine.build()
Промты с нормативной базой
       ↓  AIModel.response()
Сырые ответы LLM
       ↓  PostProcessor → InsuranceReport.merge()
Итоговый InsuranceReport
       ↓  ReportExport
client_ответ.xlsx / client_ответ.docx
```

---

## Выбор модели

Модель задаётся через `AI_PROVIDER` в `.env`. `ModelFactory.create()` возвращает нужный объект —
остальной код не знает какая модель используется (`AIModel.response(query) -> str`).

| `AI_PROVIDER` | Класс | Когда использовать |
|---|---|---|
| `ollama` | `OllamaModel` | Локальный CPU-тест или GPU-сервер с Qwen |
| `gemini` | `GeminiModel` | Облако, быстрое тестирование |
| `anthropic` | `AnthropicModel` | Облако, высокое качество |

---

## Управление контекстом (только для Ollama)

При `AI_PROVIDER=ollama` включается `ContextBuilder`, который следит за размером промта:

```
PromptEngine.build(chunk)
    │
    ├── Полная нормативная база влезает в LLM_NUM_CTX?
    │       Да → отправляем как есть
    │
    └── Нет → NormativeIndex.retrieve(chunk, budget)
            Jaccard-scoring по ключевым словам чанка
            Берём топ LLM_MAX_SECTIONS наиболее релевантных разделов
            Возвращаем только их
```

Для Gemini и Anthropic `ContextBuilder` не создаётся — вся нормативная база идёт в промт целиком
(контекст 1M / 200k токенов).

---

## Быстрый старт

### 1. Настроить `.env`

```bash
cp .env.example .env   # если есть шаблон
# или отредактировать .env напрямую
```

### 2. Запустить через Docker Compose

```bash
docker compose up -d
```

Контейнеры:
- `api` — FastAPI на порту `8001`
- `ollama` — Ollama HTTP API на порту `11434`

### 3. Убедиться что нужная модель загружена в Ollama

```bash
docker exec ollama ollama pull qwen2.5:7b      # тест на CPU
# или
docker exec ollama ollama pull qwen2.5:72b     # GPU-сервер
```

---

## API

### `POST /api/update`

Принимает путь к файлу клиента, запускает обработку, возвращает путь к результату.

**Тело запроса:**

```json
{
  "request_id": 1,
  "file_path": "/app/uploads/client.xlsx",
  "user_name": "Иванов И.И."
}
```

**Ответ (200):**

```json
{
  "request_id": 1,
  "user_name": "Иванов И.И.",
  "output_file": "/app/uploads/client_ответ.xlsx"
}
```

Выходной файл создаётся рядом с входным с суффиксом `_ответ`. Формат совпадает с входным.

---

## Конфигурация

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `NORMATIVE_BASE` | Да | — | Путь к нормативной базе (файл или папка) |
| `EXAMPLES_PATH` | Нет | `""` | Путь к папке с примерами few-shot |
| `AI_PROVIDER` | Нет | `ollama` | `ollama` / `gemini` / `anthropic` |
| `AI_TEMPERATURE` | Нет | `0.2` | Температура генерации |
| `AI_ROLE` | Да | — | Системная роль модели |
| `AI_PROMPT_TEMPLATE` | Да | — | Шаблон промта (`{role}`, `{normative_base}`, `{examples}`, `{source_text}`) |
| `LLM_BASE_URL` | Ollama | `http://ollama:11434` | Адрес Ollama (Docker или GPU-сервер) |
| `LLM_MODEL_NAME` | Ollama | `qwen2.5:7b` | Модель Ollama |
| `LLM_NUM_CTX` | Ollama | `32768` | Размер контекстного окна в токенах |
| `LLM_MAX_CHARS` | Ollama | `60000` | Лимит символов в промте |
| `LLM_MAX_SECTIONS` | Ollama | `15` | Максимум разделов нормативной базы в промте |
| `GEMINI_API_KEY` | Gemini | — | API-ключ Google Gemini |
| `AI_MODEL_NAME` | Gemini | `gemini-2.0-flash` | Модель Gemini |
| `ANTHROPIC_API_KEY` | Anthropic | — | API-ключ Anthropic |
| `ANTHROPIC_MODEL_NAME` | Anthropic | `claude-sonnet-4-6` | Модель Anthropic |

Многострочные значения в `.env` записываются в одну строку с `\n`:

```env
AI_PROMPT_TEMPLATE={role}\n\n## НОРМАТИВНАЯ БАЗА:\n{normative_base}\n\n...
```

### Типовые конфигурации

**CPU-тест (локально):**
```env
AI_PROVIDER=ollama
LLM_MODEL_NAME=qwen2.5:1.5b
LLM_NUM_CTX=4096
LLM_MAX_CHARS=10000
LLM_MAX_SECTIONS=2
```

**GPU-сервер (production):**
```env
AI_PROVIDER=ollama
LLM_BASE_URL=http://<server-ip>:11434
LLM_MODEL_NAME=qwen2.5:72b
LLM_NUM_CTX=131072
LLM_MAX_CHARS=400000
LLM_MAX_SECTIONS=15
```

**Облако (тестирование):**
```env
AI_PROVIDER=gemini
GEMINI_API_KEY=...
AI_MODEL_NAME=gemini-2.0-flash
```

---

## Нормативная база

`NORMATIVE_BASE` указывает на файл (`.docx`, `.xlsx`, `.txt`) или папку — все файлы будут загружены и объединены.

`NormativeIndex` автоматически разбивает текст на разделы по приоритету:
1. Нумерованные разделы (`1. Название`)
2. Markdown-заголовки (`# Название`)
3. Заголовки КАПСЛОКОМ
4. Абзацные подзаголовки

---

## Примеры (few-shot)

```
examples/
  001/
    client.xlsx      # запрос клиента
    response.docx    # ответ специалиста
  002/
    ...
```

Каждая подпапка — один пример. Два файла: первый по алфавиту — запрос, второй — ответ.

---

## Поддерживаемые форматы

| Формат | Чтение | Запись |
|---|---|---|
| `.xlsx` / `.xls` | Да | Да |
| `.docx` / `.doc` | Да | Да |
| `.pdf` | Да | Нет (fallback → `.docx`) |

---

## Тесты

```bash
pytest tests/ -v
```

---

## Структура проекта

```
document_assistant/
  ai/
    context_builder.py  — NormativeIndex (Jaccard-поиск), ContextBuilder (подбор под контекст)
    encoders.py         — TextEncoder
    model.py            — AIModel, OllamaModel, GeminiModel, AnthropicModel, ModelFactory
    postprocessor.py    — PostProcessor
    preprocessor.py     — DocumentPreprocessor, DocumentChunker, ExamplesLoader, ProcessingTask
    promt_builders.py   — PromptEngine, NormativeBaseLoader
  core/
    parsers.py          — DataParser (.xlsx / .docx / .pdf)
    pydantic_models.py  — APIRequest
    settings.py         — Settings (pydantic-settings)
  reports/
    report_models.py    — InsuranceReport, ReportRow
    report_export.py    — ReportExport
    writers.py          — ExcelReportWriter, WordReportWriter
  services/
    assistant.py        — AIAssistantService
main.py                 — FastAPI приложение
docker-compose.yaml
.env
tests/
```
