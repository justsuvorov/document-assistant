class DeclarationNumbering:
    """Formats the declaration reference shown in report rows and the output
    file name, per ТЗ scenarios 1 (single) and 2 (multi-row)."""

    @staticmethod
    def row_label(decl_number: str, line_index: int | None) -> str:
        return decl_number if line_index is None else f"{decl_number}/{line_index}"

    @staticmethod
    def output_filename(decl_number: str, ext: str = ".xlsx") -> str:
        return f"{decl_number} – результат проверки{ext}"
