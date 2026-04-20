# Диаграмма классов

```mermaid
classDiagram
    direction TB

    %% ── API ──────────────────────────────────────────────────────────────────
    class APIRequest {
        +request_id: int
        +file_path: str
        +user_name: str
        +priority: int
    }

    class ProcessingTask {
        +request_id: int
        +file_path: str
        +user_name: str
    }

    %% ── Orchestrator ─────────────────────────────────────────────────────────
    class AIAssistantService {
        +result() dict
    }

    %% ── Preprocessing ────────────────────────────────────────────────────────
    class Preprocessor {
        <<abstract>>
        +query() str
    }

    class DocumentPreprocessor {
        +query() str
        -_build_references() list
    }

    class ExamplesLoader {
        +load(path) list
    }

    class DataParser {
        +file_path: str
        +origin_data(path) str
        -_build_engine() Parser
    }

    class Parser {
        <<abstract>>
        +read_document(path) str
    }

    class Excel { +read_document(path) str }
    class Word  { +read_document(path) str }
    class PDF   { +read_document(path) str }

    class MarkdownTableBuilder {
        +from_rows(rows)$ str
        +normalise(rows)$ list
    }

    class WordParagraphConverter { +convert(element) str }
    class WordTableExtractor     { +extract(element) list }
    class PdfPageExtractor       { +extract(page) list }

    class Encoder {
        <<abstract>>
        +prepared_data(source) str
    }

    class TextEncoder {
        +prepared_data(source) str
    }

    class PromptEngine {
        +build(source_text, examples) str
    }

    class NormativeBaseLoader {
        +load(path) str
    }

    %% ── LLM Models ───────────────────────────────────────────────────────────
    class AIModel {
        <<abstract>>
        +response(query) str
    }

    class GeminiModel    { +response(query) str }
    class AnthropicModel { +response(query) str }
    class OllamaModel    { +response(query) str }

    class ModelFactory {
        +create()$ AIModel
    }

    %% ── Postprocessing ───────────────────────────────────────────────────────
    class PostProcessor {
        +report(raw_text) InsuranceReport
    }

    class InsuranceReport {
        +rows: list~ReportRow~
        +summary: str
        +raw_text: str
    }

    class ReportRow {
        +client_requirement: str
        +program_coverage: str
        +status: str
        +comment: str
    }

    %% ── Report Export ────────────────────────────────────────────────────────
    class ReportExport {
        +response(report) dict
    }

    class ReportWriter {
        <<abstract>>
        +write(report, path) Path
    }

    class ExcelReportWriter { +write(report, path) Path }
    class WordReportWriter  { +write(report, path) Path }

    %% ── Inheritance ──────────────────────────────────────────────────────────
    Preprocessor  <|-- DocumentPreprocessor
    Parser        <|-- Excel
    Parser        <|-- Word
    Parser        <|-- PDF
    Encoder       <|-- TextEncoder
    AIModel       <|-- GeminiModel
    AIModel       <|-- AnthropicModel
    AIModel       <|-- OllamaModel
    ReportWriter  <|-- ExcelReportWriter
    ReportWriter  <|-- WordReportWriter

    %% ── Composition ─────────────────────────────────────────────────────────
    AIAssistantService   *-- Preprocessor
    AIAssistantService   *-- PostProcessor
    AIAssistantService   *-- AIModel
    AIAssistantService   *-- ReportExport

    DocumentPreprocessor *-- DataParser
    DocumentPreprocessor *-- Encoder
    DocumentPreprocessor *-- PromptEngine
    DocumentPreprocessor *-- ExamplesLoader

    DataParser      *-- Parser
    Word            *-- WordParagraphConverter
    Word            *-- WordTableExtractor
    PDF             *-- PdfPageExtractor
    PromptEngine    *-- NormativeBaseLoader
    ReportExport    *-- ReportWriter
    InsuranceReport *-- ReportRow

    %% ── Dependencies ─────────────────────────────────────────────────────────
    Excel          ..> MarkdownTableBuilder
    Word           ..> MarkdownTableBuilder
    PDF            ..> MarkdownTableBuilder
    ExamplesLoader ..> DataParser
    ModelFactory   ..> AIModel
    PostProcessor  ..> InsuranceReport
    ReportExport   ..> InsuranceReport
```

## Обозначения

| Символ | Смысл |
|--------|-------|
| `<\|--` | Наследование / реализация абстракции |
| `*--` | Композиция (класс владеет объектом) |
| `..>` | Зависимость (использует, но не владеет) |
| `<<abstract>>` | Абстрактный класс |
| `+` | Публичный метод / поле |
| `-` | Приватный метод / поле |
| `$` | Статический метод |
