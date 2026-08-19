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

---

# Диаграмма классов — сверка деклараций с ген. полисом (cargo)

Второй, независимый пайплайн (`document_assistant/cargo/`). Использует парсеры (`DataParser`), `TextEncoder`, `AIModel`/`ModelFactory`, `DocumentChunker` и `MarkdownTableParser` из `core`/`ai` напрямую — без изменений в их интерфейсах.

```mermaid
classDiagram
    direction TB

    %% ── API ──────────────────────────────────────────────────────────────────
    class ReconcileRequest {
        +policy_folder: str
        +declaration_paths: list~str~
        +special_conditions_path: str
        +force_rebuild_matrix: bool
    }

    %% ── Discovery & filenames ────────────────────────────────────────────────
    class PolicyFilenameParser {
        +parse(file_path) PolicySource
    }

    class DeclarationFilenameParser {
        +parse_number(file_path) str
    }

    class PolicyFolderScanner {
        +scan(policy_folder) list~PolicySource~
    }

    %% ── Rules matrix ─────────────────────────────────────────────────────────
    class RulesMatrixService {
        +get_or_build(policy_folder, force_rebuild) tuple
    }

    class RulesMatrixCache {
        +fingerprint(sources) str
        +load(policy_folder) RulesMatrix
        +save(policy_folder, matrix) Path
    }

    class RulesMatrixBuilder {
        +build(policy_folder, sources) RulesMatrix
    }

    class ClauseMerger {
        +merge(sources_with_candidates) list~PolicyClause~
    }

    class MatrixPromptEngine {
        +build(source_text) str
    }

    class MatrixPostProcessor {
        +parse(raw_text) list~RawClause~
    }

    class RulesMatrix {
        +clauses: list~PolicyClause~
        +fingerprint: str
        +to_prompt_block() str
    }

    class PolicyClause {
        +clause_id: str
        +effective_text: str
        +source_label: str
        +effective_from: date
    }

    class PolicySource {
        +kind: str
        +ds_number: int
        +valid_from: date
        +sort_key() tuple
    }

    %% ── Declaration classification ───────────────────────────────────────────
    class DeclarationTypeClassifier {
        +classify(markdown_text) DeclarationType
    }

    class DeclarationNumbering {
        +row_label(decl_number, line_index)$ str
        +output_filename(decl_number)$ str
    }

    %% ── Special conditions ───────────────────────────────────────────────────
    class SpecialConditionsLoader {
        +load(policy_folder, explicit_path) str
    }

    %% ── Reconciliation ───────────────────────────────────────────────────────
    class ReconciliationPromptEngine {
        +build(rules_matrix_block, special_conditions, source_text) str
    }

    class ReconciliationPostProcessor {
        +parse(raw_text, declaration_number) ReconciliationReport
    }

    class ReconciliationReport {
        +rows: list~ReconciliationRow~
        +merge(declaration_number, reports)$ ReconciliationReport
    }

    class ReconciliationRow {
        +declaration_ref: str
        +field_name: str
        +matched_policy_clause: str
        +result: str
        +comment: str
    }

    class ReconciliationExcelWriter {
        +write(report, output_path, special_conditions_text) Path
    }

    class ReconciliationOutputResolver {
        +resolve(declaration_path, declaration_number)$ Path
    }

    class PeriodMonthResolver {
        +warn_if_mismatched(declaration_path, period_start)$ str
    }

    class CargoReconciliationService {
        +result(request) dict
    }

    %% ── Composition ──────────────────────────────────────────────────────────
    RulesMatrixService   *-- PolicyFolderScanner
    RulesMatrixService   *-- RulesMatrixCache
    RulesMatrixService   *-- RulesMatrixBuilder
    RulesMatrixBuilder   *-- MatrixPromptEngine
    RulesMatrixBuilder   *-- MatrixPostProcessor
    RulesMatrixBuilder   *-- ClauseMerger
    RulesMatrix          *-- PolicyClause
    PolicyFolderScanner  *-- PolicyFilenameParser
    ClauseMerger         ..> PolicySource

    CargoReconciliationService *-- ReconciliationPromptEngine
    CargoReconciliationService *-- ReconciliationPostProcessor
    CargoReconciliationService *-- ReconciliationExcelWriter
    CargoReconciliationService *-- DeclarationTypeClassifier
    CargoReconciliationService *-- DeclarationFilenameParser
    CargoReconciliationService ..> RulesMatrix
    CargoReconciliationService ..> DeclarationNumbering
    CargoReconciliationService ..> ReconciliationOutputResolver
    CargoReconciliationService ..> PeriodMonthResolver
    CargoReconciliationService ..> SpecialConditionsLoader
    ReconciliationReport *-- ReconciliationRow
    ReconciliationPostProcessor ..> ReconciliationReport
```
