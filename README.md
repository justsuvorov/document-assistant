# Document Assistant

Сервис для автоматической обработки клиентских запросов по страхованию ДМС.

Клиент присылает документ (Excel или Word) с перечнем необходимых страховых услуг.
Сервис сопоставляет их с нормативной базой страховых программ, анализирует каждое требование
и возвращает структурированный ответ с отметками «Есть / Нет / Частично».

---

## Компоненты

| Компонент | Описание |
|---|---|
| `main.py` | FastAPI-сервер, эндпоинты `/api/update`, `/api/estimate`, `/api/rebuild` |
| `app/main.py` | Десктопное GUI-приложение «ВСК ДМС-ассистент» (PyEdifice + PySide6) |
| `docker-compose.yaml` | Контейнер `api` (FastAPI :8001) + опциональный `ollama` (:11434) |

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
       ├── ModelFactory                — выбирает модель по AI_PROVIDER
       │       ├── OllamaModel         — локальный CPU или удалённый GPU-сервер
       │       ├── GeminiModel         — Google Gemini API (облако)
       │       └── AnthropicModel      — Anthropic Claude API (облако, с retry по retry-after)
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
       ↓  AIModel.response()  ×N  (с retry при 429/503)
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

GUI-приложение копирует выбранный нормативный файл в директорию `normative_base/`. Чтобы замена работала корректно, используйте одно и то же имя файла при обновлении базы.

---

## Выбор модели

Модель задаётся через `AI_PROVIDER` в `.env`. `ModelFactory.create()` возвращает нужный объект —
остальной код не знает какая модель используется (`AIModel.response(query) -> str`).

| `AI_PROVIDER` | Класс | Когда использовать |
|---|---|---|
| `ollama` | `OllamaModel` | Локальный CPU-тест или GPU-сервер с Qwen |
| `gemini` | `GeminiModel` | Облако, самый быстрый и дешёвый вариант |
| `anthropic` | `AnthropicModel` | Облако, высокое качество |

### Сравнение облачных моделей (полный прогон, ~64 чанка)

| Модель | Стоимость | Время | Rate limit T1 |
|---|---|---|---|
| Claude Sonnet 4.6 | ~$10–12 | ~3.5 ч | 30k TPM |
| Claude Haiku 4.5 | ~$2–3 | ~1.5 ч | ~50k TPM |
| Gemini 2.0 Flash | ~$0.3 | ~10 мин | высокий |

`AnthropicModel` поддерживает автоматический retry при 429 с использованием заголовка `retry-after` из ответа API (до 5 попыток).

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
       │       Каждый раздел → отдельный чанк
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

`ContextBuilder` работает для **всех провайдеров** и следит за тем, чтобы нормативная база
помещалась в контекстное окно модели. Бюджет задаётся отдельно для каждого провайдера.

```
PromptEngine.build(chunk)
    │
    ├── Полная нормативная база помещается в бюджет (LLM_NUM_CTX / GEMINI_NUM_CTX / ...)?
    │       Да → отправляем полностью
    │
    └── Нет → NormativeIndex.retrieve(chunk, budget)
            Jaccard-scoring по ключевым словам чанка
            Берём топ LLM_MAX_SECTIONS наиболее релевантных разделов
            Возвращаем только их (RAG)
            Fallback: если ни один не влезает → обрезаем первый до бюджета
```

| Провайдер | Переменная бюджета | Типовое значение |
|---|---|---|
| Ollama | `LLM_NUM_CTX` | 32 768 токенов |
| Gemini | `GEMINI_NUM_CTX` | 1 000 000 токенов |
| Anthropic | `ANTHROPIC_NUM_CTX` | 200 000 токенов |

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
  "model": "claude-haiku-4-5-20251001",
  "provider": "anthropic",
  "chunks": [
    {"index": 1, "raw_response": "...", "rows_parsed": 25},
    ...
  ]
}
```

Для переобработки без повторного вызова LLM используется эндпоинт `/api/rebuild`.

---

## GUI-приложение (ВСК ДМС-ассистент)

Локальное десктопное приложение на PyEdifice + PySide6.

```bash
python app/main.py
```

**Функциональность:**
- Выбор файла нормативной базы (копируется в `normative_base/`)
- Выбор файла клиента (копируется в `uploads/`)
- **Кнопка «Оценить время работы»** — анализирует файл через `/api/estimate`, показывает количество чанков и расчётное время
- **Слайдер 1–100%** — ограничивает долю документа для обработки (уменьшает время)
- Кнопка «Подготовить» — запускает обработку с учётом слайдера
- Прогресс-бар с оценкой времени
- Кнопка «Открыть результат» появляется после завершения обработки

Приложение ожидает запущенный FastAPI-контейнер на порту 8001.

---

## Быстрый старт

### 1. Настроить `.env`

```bash
# или отредактировать .env напрямую
```

### 2. Запустить через Docker Compose

```bash
docker compose up -d
```

Контейнеры:
- `api` — FastAPI на порту `8001`
- `ollama` — Ollama HTTP API на порту `11434`

### 3. Запустить GUI

```bash
python app/main.py
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

| Переменная | По умолчанию | Описание |
|---|---|---|
| `NORMATIVE_BASE` | — | Путь к нормативной базе (файл или папка). Читается при каждом запросе. |
| `EXAMPLES_PATH` | `""` | Путь к папке с примерами few-shot |
| `AI_PROVIDER` | `ollama` | `ollama` / `gemini` / `anthropic` |
| `AI_TEMPERATURE` | `0.2` | Температура генерации |
| `AI_ROLE` | — | Системная роль модели |
| `AI_PROMPT_TEMPLATE` | — | Шаблон промта |
| **Разбивка документа** | | |
| `LLM_MAX_CHARS` | `60000` | Максимум символов из клиентского файла. Для больших таблиц — `2200000`. |
| `LLM_BATCH_SIZE` | `25` | Строк в одном батче при разбивке таблицы |
| `LLM_MAX_CHUNKS` | `0` | Лимит чанков (`0` = все). Для отладки или переопределяется через `max_chunks` в запросе. |
| `LLM_MAX_SECTIONS` | `15` | Максимум разделов нормативной базы в промте (RAG-лимит) |
| **Ollama** | | |
| `LLM_BASE_URL` | `http://ollama:11434` | Адрес Ollama |
| `LLM_MODEL_NAME` | `qwen2.5:7b` | Модель Ollama |
| `LLM_NUM_CTX` | `32768` | Контекстное окно в токенах |
| **Gemini** | | |
| `GEMINI_API_KEY` | — | API-ключ Google Gemini |
| `AI_MODEL_NAME` | `gemini-2.0-flash` | Модель Gemini |
| `GEMINI_NUM_CTX` | `1000000` | Бюджет токенов для ContextBuilder |
| **Anthropic** | | |
| `ANTHROPIC_API_KEY` | — | API-ключ Anthropic |
| `ANTHROPIC_MODEL_NAME` | `claude-sonnet-4-6` | Модель Anthropic |
| `ANTHROPIC_NUM_CTX` | `200000` | Бюджет токенов для ContextBuilder |

### Типовые конфигурации

**CPU-тест (локально):**
```env
AI_PROVIDER=ollama
LLM_MODEL_NAME=qwen2.5:1.5b
LLM_NUM_CTX=4096
LLM_MAX_CHARS=10000
LLM_MAX_SECTIONS=2
LLM_BATCH_SIZE=10
LLM_MAX_CHUNKS=1
```

**Облако Anthropic Haiku (оптимум цена/качество):**
```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL_NAME=claude-haiku-4-5-20251001
ANTHROPIC_NUM_CTX=200000
LLM_MAX_CHARS=2200000
LLM_BATCH_SIZE=25
LLM_MAX_SECTIONS=10
LLM_MAX_CHUNKS=0
```

**Облако Anthropic Sonnet (высокое качество):**
```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL_NAME=claude-sonnet-4-6
ANTHROPIC_NUM_CTX=200000
LLM_MAX_CHARS=2200000
LLM_BATCH_SIZE=25
LLM_MAX_SECTIONS=15
LLM_MAX_CHUNKS=0
```

**Облако Gemini Flash (быстро и дёшево):**
```env
AI_PROVIDER=gemini
GEMINI_API_KEY=...
AI_MODEL_NAME=gemini-2.0-flash
LLM_MAX_CHARS=2200000
LLM_BATCH_SIZE=25
GEMINI_NUM_CTX=500000
LLM_MAX_SECTIONS=15
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
    model.py            — AIModel, OllamaModel, GeminiModel, AnthropicModel (retry), ModelFactory
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
app/
  main.py               — GUI «ВСК ДМС-ассистент» (оценка, слайдер, прогресс)
  assets/               — логотип, шрифт
main.py                 — FastAPI (/api/update, /api/estimate, /api/rebuild)
docker-compose.yaml
.env
reprocess_from_debug.py — переобработка из кэша без LLM (CLI)
tests/
```
