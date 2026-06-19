# Диаграмма классов

```mermaid
classDiagram
    direction TB

    %% ── API ──────────────────────────────────────────────────────────────────
    class APIRequest {
        +request_id: int
        +file_path: str
        +user_name: str
    }

    class ProcessingTask {
        +request_id: int
        +file_path: str
        +user_name: str
    }

    %% ── Orchestrator ─────────────────────────────────────────────────────────
    class AIAssistantService {
        +result() dict
        +rebuild_from_json() dict
    }

    %% ── Preprocessing ────────────────────────────────────────────────────────
    class DocumentPreprocessor {
        +queries() list~str~
        +query() str
    }

    class DocumentChunker {
        +split(text) list~str~
    }

    class ExamplesLoader {
        +load(path) list~str~
    }

    class DataParser {
        +origin_data(path) str
    }

    class Parser {
        <<abstract>>
        +read_document(path) str
    }

    class Excel { +read_document(path) str }
    class Word  { +read_document(path) str }
    class PDF   { +read_document(path) str }

    class TextEncoder {
        +prepared_data(source) str
    }

    class PromptEngine {
        +build(source_text, examples) str
    }

    class NormativeBaseLoader {
        +load(path) str
    }

    class NormativeIndex {
        +retrieve(query, budget) str
        +section_count int
    }

    class ContextBuilder {
        +build(template, role, examples, source_text) str
    }

    %% ── LLM Models ───────────────────────────────────────────────────────────
    class AIModel {
        <<abstract>>
        +response(query) str
    }

    class QwenModel {
        +response(query) str
        -_call_api(query) str
    }

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
        +merge(reports)$ InsuranceReport
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

    class ExcelReportWriter {
        +write(report, path) Path
        -_find_row_global(requirement, index) tuple
    }

    class WordReportWriter {
        +write(report, path) Path
    }

    %% ── Inheritance ──────────────────────────────────────────────────────────
    Parser        <|-- Excel
    Parser        <|-- Word
    Parser        <|-- PDF
    AIModel       <|-- QwenModel
    ReportWriter  <|-- ExcelReportWriter
    ReportWriter  <|-- WordReportWriter

    %% ── Composition ─────────────────────────────────────────────────────────
    AIAssistantService   *-- DocumentPreprocessor
    AIAssistantService   *-- PostProcessor
    AIAssistantService   *-- AIModel
    AIAssistantService   *-- ReportExport

    DocumentPreprocessor *-- DataParser
    DocumentPreprocessor *-- TextEncoder
    DocumentPreprocessor *-- PromptEngine
    DocumentPreprocessor *-- DocumentChunker
    DocumentPreprocessor *-- ExamplesLoader

    DataParser    *-- Parser
    PromptEngine  *-- NormativeBaseLoader
    PromptEngine  *-- NormativeIndex
    PromptEngine  *-- ContextBuilder
    ReportExport  *-- ReportWriter
    InsuranceReport *-- ReportRow

    %% ── Dependencies ─────────────────────────────────────────────────────────
    ModelFactory   ..> AIModel
    PostProcessor  ..> InsuranceReport
    ReportExport   ..> InsuranceReport
    ExcelReportWriter ..> NormativeIndex
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
