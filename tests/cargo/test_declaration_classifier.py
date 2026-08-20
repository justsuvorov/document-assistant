from document_assistant.cargo.declaration_classifier import DeclarationType, DeclarationTypeClassifier


class TestDeclarationTypeClassifier:
    def setup_method(self):
        self.classifier = DeclarationTypeClassifier()

    def test_single_row_table_is_single(self):
        text = (
            "| Груз | Маршрут |\n"
            "|---|---|\n"
            "| Оборудование | Москва-СПб |\n"
        )
        assert self.classifier.classify(text) == DeclarationType.SINGLE

    def test_multi_row_table_is_multi(self):
        text = (
            "| Груз | Маршрут |\n"
            "|---|---|\n"
            "| Оборудование | Москва-СПб |\n"
            "| Металл | СПб-Казань |\n"
            "| Текстиль | Казань-Уфа |\n"
        )
        assert self.classifier.classify(text) == DeclarationType.MULTI

    def test_no_table_is_single(self):
        text = "Декларация на перевозку оборудования по маршруту Москва-СПб."
        assert self.classifier.classify(text) == DeclarationType.SINGLE

    def test_empty_text_is_single(self):
        assert self.classifier.classify("") == DeclarationType.SINGLE
