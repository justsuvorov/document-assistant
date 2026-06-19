# Document Assistant — Qwen Release

Сервис для автоматической обработки клиентских запросов по страхованию ДМС.

Клиент присылает документ (Excel или Word) с перечнем необходимых страховых услуг.
Сервис сопоставляет их с нормативной базой страховых программ, анализирует каждое требование
и возвращает структурированный ответ с отметками **«Есть / Нет / Частично»**.

---

## Компоненты

| Компонент | Описание |
|---|---|
| `main.py` | FastAPI-сервер, эндпоинты `/api/update`, `/api/estimate`, `/api/rebuild` |
| `docker-compose.yaml` | Контейнер `api` (FastAPI :8001) с подключением к Qwen |

---

## Архитектура

```
POST /api/update
       │
       ▼
 AIAssistantService
       │
       ├── DocumentPreprocessor
       │       ├── DataParser          — читает файл клиента (.xlsx / .docx / .pdf) → текст
       │       ├── TextEncoder         — нормализует текст, обрезает до LLM_MAX_CHARS
       │       ├── DocumentChunker     — делит на чанки (разделы / заголовки / батчи строк)
       │       └── PromptEngine        — собирает промт для каждого чанка
       │               └── ContextBuilder  — RAG: подбирает нормативную базу под бюджет
       │                       └── NormativeIndex — Jaccard-поиск по разделам базы
       │
       ├── ModelFactory                — QwenModel (OpenAI-compatible API)
       │
       ├── PostProcessor               — парсит ответ LLM → InsuranceReport
       │       └── InsuranceReport.merge() — объединяет ответы по всем чанкам
       │
       └── ReportExport                — сохраняет результат в формате клиента
               ├── ExcelReportWriter   — .xlsx (копирует исходник, пишет в столбцы 2-4)
               └── WordReportWriter    — .docx
```

---

## Поток данных

```
client.xlsx / client.docx / client.pdf
       ↓  DataParser  (newlines в ячейках → пробел)
Сырой текст
       ↓  TextEncoder  (обрезка до LLM_MAX_CHARS символов)
Нормализованный текст
       ↓  DocumentChunker  (стратегия — см. раздел ниже)
[chunk1, chunk2, ..., chunkN]  ← ограничивается max_chunks если задан
       ↓  для каждого чанка: PromptEngine.build()
Промты с нормативной базой (RAG через ContextBuilder)
       ↓  QwenModel.response()  ×N  (с retry при overload)
Сырые ответы LLM
       ↓  сохраняются в *_llm_debug.md и *_llm_output.json
       ↓  PostProcessor → InsuranceReport.merge()
Итоговый InsuranceReport
       ↓  ReportExport
client_ответ.xlsx  —  исходный файл + 3 новых столбца (2, 3, 4)
client_ответ.docx  —  новый файл с таблицей (для Word/PDF/прочих)
```

---

## Жизненный цикл нормативной базы

**При старте FastAPI ничего не загружается в память.** `settings = Settings()` читает только `.env` — запоминает путь, не сам файл.

При каждом запросе `POST /api/update` вся цепочка строится заново:

```
_build_service(request)
  └─ PromptEngine.__init__()
       └─ NormativeBaseLoader.load(NORMATIVE_BASE)   ← читает с диска
       └─ NormativeIndex(text)                        ← индексирует в память
  └─ DataParser(file_path)                            ← читает клиентский файл
```

Это значит:
- **Смена нормативной базы** вступает в силу немедленно при следующем запросе — перезапуск сервера не нужен.
- **`NORMATIVE_BASE` — директория**: `NormativeBaseLoader` читает все файлы в ней и конкатенирует. Если туда скопировать новый файл, не удалив старый, оба попадут в промт.
- **`NORMATIVE_BASE` — файл**: перезаписи конкретного файла достаточно.

---

## Разбивка документа на чанки (DocumentChunker)

Ключевое бизнес-требование: **ответ на каждое требование клиента отдельно, без группировок**.
Клиент загружает таблицу с N строками — система возвращает ровно N строк ответа.

Для больших документов и контроля размера промта DocumentChunker делит текст на части.
Стратегии применяются по приоритету (первая сработавшая используется):

```
Нормализованный текст
       │
       ├─ 1. Нумерованные разделы  (строки вида "1. Название")
       │       Сгруппированы батчами по LLM_BATCH_SIZE
       │
       ├─ 2. Markdown-заголовки  (строки, начинающиеся с #)
       │       Каждый заголовок + его тело → чанк
       │       Если внутри есть большая таблица → применяется стратегия 3
       │
       ├─ 3. Батчинг строк таблицы  (Markdown-таблица > LLM_BATCH_SIZE строк)
       │       Заголовок таблицы повторяется в каждом батче
       │       Пример: 322 строки, LLM_BATCH_SIZE=25 → 13 чанков по 25 строк
       │
       └─ 4. Fallback  — весь документ как один чанк
```

**Важно:** ячейки Excel с переносами строк (`\n`) нормализуются в пробел при парсинге — иначе строки таблицы выходят многострочными и батчинг не срабатывает.

Каждый чанк обрабатывается отдельным запросом к LLM. Ответы объединяются в правильном порядке
через `InsuranceReport.merge()`.

---

## Управление контекстом (ContextBuilder)

`ContextBuilder` следит за тем, чтобы нормативная база помещалась в контекстное окно модели.

```
PromptEngine.build(chunk)
    │
    ├── Полная нормативная база помещается в бюджет (QWEN_NUM_CTX)?
    │       Да → отправляем полностью
    │
    └── Нет → NormativeIndex.retrieve(chunk, budget)
            Jaccard-scoring по ключевым словам чанка
            Берём топ LLM_MAX_SECTIONS наиболее релевантных разделов
            Возвращаем только их (RAG)
            Fallback: если ни один не влезает → обрезаем первый до бюджета
```

**Qwen контекстное окно:** `QWEN_NUM_CTX=128000` токенов

---

## Сопоставление строк в Excel (ExcelReportWriter)

При записи ответа в `.xlsx` результаты LLM сопоставляются с исходными строками по тексту,
а не по позиции — это защищает от сдвига при пропуске строк моделью.

Алгоритм поиска строки (четыре уровня, первое совпадение используется):

```
1. Точное совпадение нормализованного текста
2. Суффиксное совпадение — источник является хвостом LLM-строки после разделителя
   (: , ; .) — решает случай "Первичные приёмы: аллерголог-иммунолог" → "аллерголог-иммунолог"
3. Префиксное совпадение — источник начинается с LLM-строки (≥ 10 символов)
4. Jaccard-перекрытие слов ≥ 75 % при соотношении длин ≤ 3:1
```

Дедупликация: каждая исходная строка аннотируется не более одного раза (`used_locations`).
Объединённые ячейки (`MergedCell`) пропускаются при записи.
Аннотации пишутся в столбцы 2, 3, 4 на каждом листе, где были найдены совпадения.
Многолистовые файлы поддерживаются: индекс строк строится глобально по всем листам.

---

## Кэширование ответов LLM

После каждой обработки создаются два файла рядом с исходником:

- `*_llm_debug.md` — сырые ответы по чанкам в читаемом виде (для отладки и переобработки)
- `*_llm_output.json` — структурированный JSON с метаданными (провайдер, модель, время, чанки)

JSON-формат:
```json
{
  "file_path": "/app/uploads/client.xlsx",
  "processed_at": "2026-05-20T10:51:00+00:00",
  "model": "Qwen3.6-35B-A3B",
  "provider": "qwen",
  "chunks": [
    {"index": 1, "raw_response": "...", "rows_parsed": 25},
    ...
  ]
}
```

Для переобработки без повторного вызова LLM используется эндпоинт `/api/rebuild`.

---

## Быстрый старт

### 1. Настроить `.env`

```bash
# Обязательные переменные
NORMATIVE_BASE=/app/normative_base
EXAMPLES_PATH=/app/examples

AI_ROLE="Ты — опытный специалист по страхованию..."
AI_PROMPT_TEMPLATE="{role}\n\n## НОРМАТИВНАЯ БАЗА:\n{normative_base}\n\n..."

# Модель Qwen
QWEN_API_URL=https://model-1.ai-api.vsk.ru/v1/completions
QWEN_MODEL_NAME=Qwen3.6-35B-A3B
QWEN_MAX_TOKENS=4096
QWEN_NUM_CTX=128000

# Обработка документов
LLM_MAX_CHARS=2200000
LLM_MAX_SECTIONS=10
LLM_MAX_CHUNKS=0
LLM_BATCH_SIZE=25
AI_TEMPERATURE=0.2
```

### 2. Запустить через Docker Compose

```bash
docker compose up -d
```

Контейнер:
- `api` — FastAPI на порту `8001`

### 3. Проверить здоровье

```bash
curl http://localhost:8001/docs
```

---

## API

### `POST /api/update`

Запускает обработку файла, возвращает путь к результату.

**Тело запроса:**
```json
{
  "request_id": 1,
  "file_path": "/app/uploads/client.xlsx",
  "user_name": "Иванов И.И.",
  "max_chunks": 0
}
```
`max_chunks=0` — обработать все чанки (по умолчанию). Положительное число ограничивает обработку.

**Ответ (200):**
```json
{
  "request_id": 1,
  "user_name": "Иванов И.И.",
  "output_file": "/app/uploads/client_ответ.xlsx"
}
```

---

### `POST /api/estimate`

Анализирует файл без вызова LLM, возвращает оценку объёма и времени.

**Тело запроса:**
```json
{ "file_path": "/app/uploads/client.xlsx" }
```

**Ответ (200):**
```json
{
  "chunk_count": 62,
  "estimated_seconds": 7440,
  "total_chars": 2144067,
  "processed_chars": 2144067
}
```

---

### `POST /api/rebuild`

Собирает Excel из кэшированного JSON без повторного вызова LLM.
Возвращает 422 если `json_path` и `file_path` относятся к разным файлам.

**Тело запроса:**
```json
{
  "request_id": 1,
  "json_path": "/app/uploads/client_llm_output.json",
  "file_path": "/app/uploads/client.xlsx",
  "user_name": "Иванов И.И."
}
```

---

## Конфигурация

| Переменная | Описание |
|---|---|
| `NORMATIVE_BASE` | Путь к нормативной базе (файл или папка). Читается при каждом запросе. |
| `EXAMPLES_PATH` | Путь к папке с примерами few-shot (опционально) |
| `AI_ROLE` | Системная роль модели |
| `AI_PROMPT_TEMPLATE` | Шаблон промта |
| `LLM_MAX_CHARS` | Максимум символов из клиентского файла (обычно 2 200 000) |
| `LLM_BATCH_SIZE` | Строк в одном батче при разбивке таблицы (обычно 25) |
| `LLM_MAX_CHUNKS` | Лимит чанков (0 = все) |
| `LLM_MAX_SECTIONS` | Максимум разделов нормативной базы в промте (RAG-лимит) |
| `AI_TEMPERATURE` | Температура генерации (обычно 0.2) |
| `QWEN_API_URL` | Адрес API Qwen |
| `QWEN_MODEL_NAME` | Модель Qwen |
| `QWEN_MAX_TOKENS` | Максимум токенов в ответе |
| `QWEN_NUM_CTX` | Контекстное окно в токенах (128 000) |

---

## Нормативная база

`NORMATIVE_BASE` указывает на файл (`.docx`, `.xlsx`, `.txt`) или папку — все файлы будут загружены и объединены.

`NormativeIndex` автоматически разбивает текст на разделы по приоритету:
1. Нумерованные разделы (`1. Название`)
2. Markdown-заголовки (`# Название`)
3. Заголовки КАПСЛОКОМ
4. Абзацные подзаголовки

---

## Поддерживаемые форматы

| Формат | Чтение | Запись |
|---|---|---|
| `.xlsx` / `.xls` | Да | Да |
| `.docx` / `.doc` | Да | Да |
| `.pdf` | Да | Нет (fallback → `.docx`) |

---

## Структура проекта

```
document_assistant/
  ai/
    context_builder.py  — NormativeIndex (Jaccard-поиск), ContextBuilder
    encoders.py         — TextEncoder
    model.py            — AIModel, QwenModel (retry), ModelFactory
    postprocessor.py    — PostProcessor
    preprocessor.py     — DocumentPreprocessor, DocumentChunker, ProcessingTask
    promt_builders.py   — PromptEngine, NormativeBaseLoader
  core/
    parsers.py          — DataParser (.xlsx / .docx / .pdf), нормализация ячеек
    pydantic_models.py  — APIRequest, EstimateRequest, RebuildRequest
    settings.py         — Settings (pydantic-settings)
  reports/
    report_models.py    — InsuranceReport, ReportRow
    report_export.py    — ReportExport
    writers.py          — ExcelReportWriter (4-уровневый matching, MergedCell), WordReportWriter
  services/
    assistant.py        — AIAssistantService, сохранение JSON/debug, rebuild_from_json
main.py                 — FastAPI (/api/update, /api/estimate, /api/rebuild)
docker-compose.yaml
.env
requirements.txt
tests/
```
