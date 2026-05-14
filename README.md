# Document Assistant

Сервис для автоматической обработки клиентских запросов по страхованию ДМС.

Клиент присылает документ (Excel или Word) с перечнем необходимых страховых услуг.
Сервис сопоставляет их с нормативной базой страховых программ, анализирует каждое требование
и возвращает структурированный ответ с отметками «Есть / Нет / Частично».

---

## Компоненты

| Компонент | Описание |
|---|---|
| `main.py` | FastAPI-сервер, эндпоинт `POST /api/update` |
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
       │       └── AnthropicModel      — Anthropic Claude API (облако)
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
       ↓  DataParser
Сырой текст
       ↓  TextEncoder  (обрезка до LLM_MAX_CHARS символов)
Нормализованный текст
       ↓  DocumentChunker  (стратегия — см. раздел ниже)
[chunk1, chunk2, ..., chunkN]
       ↓  для каждого чанка: PromptEngine.build()
Промты с нормативной базой (RAG через ContextBuilder)
       ↓  AIModel.response()  ×N  (последовательно, синхронный эндпоинт)
Сырые ответы LLM  (N строк-ответов)
       ↓  PostProcessor → InsuranceReport.merge()
Итоговый InsuranceReport  (все строки объединены в порядке чанков)
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
| `gemini` | `GeminiModel` | Облако, быстрое тестирование |
| `anthropic` | `AnthropicModel` | Облако, высокое качество |

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

Каждый чанк обрабатывается отдельным запросом к LLM. Ответы объединяются в правильном порядке
через `InsuranceReport.merge()`.

Для отладки при каждом запросе создаётся файл `<имя_клиента>_debug.md` рядом с исходником.

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

Алгоритм поиска строки (три уровня):

```
1. Точное совпадение нормализованного текста
2. Один текст является префиксом другого (≥ 10 символов)
3. Jaccard-перекрытие слов ≥ 75 % (при ≥ 3 словах в запросе)
```

Аннотации пишутся в столбцы 2, 3, 4 на каждом листе, где были найдены совпадения.
Многолистовые файлы поддерживаются: индекс строк строится глобально по всем листам.

---

## GUI-приложение (ВСК ДМС-ассистент)

Локальное десктопное приложение на PyEdifice + PySide6.

```bash
cd app
pip install -r requirements.txt
python main.py
```

**Функциональность:**
- Выбор файла нормативной базы (копируется в `normative_base/`)
- Выбор файла клиента (копируется в `uploads/`)
- Кнопка «Подготовить» — отправляет запрос на `http://localhost:8001/api/update`
- Прогресс-бар с оценкой времени (на основе количества строк в Excel)
- Кнопка «Открыть результат» появляется после завершения обработки

Приложение ожидает запущенный FastAPI-контейнер на порту 8001.

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

### 4. Запустить GUI

```bash
cd app && python main.py
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
| `NORMATIVE_BASE` | Да | — | Путь к нормативной базе (файл или папка). Читается при каждом запросе. |
| `EXAMPLES_PATH` | Нет | `""` | Путь к папке с примерами few-shot |
| `AI_PROVIDER` | Нет | `ollama` | `ollama` / `gemini` / `anthropic` |
| `AI_TEMPERATURE` | Нет | `0.2` | Температура генерации |
| `AI_ROLE` | Да | — | Системная роль модели |
| `AI_PROMPT_TEMPLATE` | Да | — | Шаблон промта (`{role}`, `{normative_base}`, `{examples}`, `{source_text}`) |
| **Разбивка и размер документа** | | | |
| `LLM_MAX_CHARS` | Нет | `60000` | Максимум символов из клиентского файла перед разбивкой. Увеличьте до `400000` для больших таблиц. |
| `LLM_BATCH_SIZE` | Нет | `25` | Строк в одном батче при разбивке таблицы (стратегия 3) |
| `LLM_MAX_CHUNKS` | Нет | `0` | Лимит чанков для обработки (`0` = все). Полезно при отладке. |
| **Ollama** | | | |
| `LLM_BASE_URL` | Ollama | `http://ollama:11434` | Адрес Ollama (Docker или GPU-сервер) |
| `LLM_MODEL_NAME` | Ollama | `qwen2.5:7b` | Модель Ollama |
| `LLM_NUM_CTX` | Ollama | `32768` | Контекстное окно в токенах |
| `LLM_MAX_SECTIONS` | Все | `15` | Максимум разделов нормативной базы в одном промте (RAG-лимит) |
| **Gemini** | | | |
| `GEMINI_API_KEY` | Gemini | — | API-ключ Google Gemini |
| `AI_MODEL_NAME` | Gemini | `gemini-2.0-flash` | Модель Gemini |
| `GEMINI_NUM_CTX` | Gemini | `1000000` | Бюджет токенов для нормативной базы в ContextBuilder |
| **Anthropic** | | | |
| `ANTHROPIC_API_KEY` | Anthropic | — | API-ключ Anthropic |
| `ANTHROPIC_MODEL_NAME` | Anthropic | `claude-sonnet-4-6` | Модель Anthropic |
| `ANTHROPIC_NUM_CTX` | Anthropic | `200000` | Бюджет токенов для нормативной базы в ContextBuilder |

Многострочные значения в `.env` записываются в одну строку с `\n`:

```env
AI_PROMPT_TEMPLATE={role}\n\n## НОРМАТИВНАЯ БАЗА:\n{normative_base}\n\n...
```

### Типовые конфигурации

**CPU-тест (локально, ограниченная мощность):**
```env
AI_PROVIDER=ollama
LLM_MODEL_NAME=qwen2.5:1.5b
LLM_NUM_CTX=4096
LLM_MAX_CHARS=10000
LLM_MAX_SECTIONS=2
LLM_BATCH_SIZE=10
LLM_MAX_CHUNKS=1        # обработать только первый чанк для проверки
```

**GPU-сервер (production):**
```env
AI_PROVIDER=ollama
LLM_BASE_URL=http://<server-ip>:11434
LLM_MODEL_NAME=qwen2.5:72b
LLM_NUM_CTX=131072
LLM_MAX_CHARS=400000
LLM_MAX_SECTIONS=15
LLM_BATCH_SIZE=25
```

**Облако Gemini (рекомендуется для тестирования):**
```env
AI_PROVIDER=gemini
GEMINI_API_KEY=...
AI_MODEL_NAME=gemini-2.5-flash-lite
LLM_MAX_CHARS=400000
LLM_BATCH_SIZE=25
GEMINI_NUM_CTX=500000
LLM_MAX_SECTIONS=2
```

**Облако Anthropic (высокое качество):**
```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL_NAME=claude-sonnet-4-6
LLM_MAX_CHARS=400000
LLM_BATCH_SIZE=25
ANTHROPIC_NUM_CTX=200000
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
    writers.py          — ExcelReportWriter (multi-sheet, text matching), WordReportWriter
  services/
    assistant.py        — AIAssistantService
app/
  main.py               — GUI «ВСК ДМС-ассистент» (PyEdifice + PySide6)
  assets/               — иконки и изображения
  requirements.txt      — зависимости GUI
main.py                 — FastAPI приложение
docker-compose.yaml
.env
tests/
```
