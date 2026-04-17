import re

class PostProcessor:
    def __init__(self):
        # Список паттернов, которые мы не хотим видеть в финальном посте
        self._trash_patterns = [
            r"^(Вот|Готовый|Ваш|Исправленный|Текст|Результат).+?:\n+",
            r"^Конечно,.+?\n+",
            r"^Держи.+?\n+",
            r"Надеюсь, это поможет.*$",
            r"Если нужно что-то исправить.*$"
        ]

    def report(self, raw_text: str) -> str:
        """

        """
        if not raw_text:
            return ""

        # 1. Удаляем Markdown блоки кода (```), если Gemini обернула в них текст
        # Это часто бывает, когда модель пытается быть "аккуратной"
        clean_text = re.sub(r'```(?:\w+)?\n?', '', raw_text)
        clean_text = clean_text.replace('```', '')

        # 2. Удаляем лишние кавычки по краям (если модель процитировала сама себя)
        clean_text = clean_text.strip().strip('"').strip("'")

        # 3. Чистим вводные фразы ("Вот ваш пост:", "Конечно, я помогу...")
        for pattern in self._trash_patterns:
            clean_text = re.sub(pattern, "", clean_text, flags=re.IGNORECASE | re.MULTILINE)

        # 4. Нормализуем пробелы и пустые строки (не более двух переносов подряд)
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)
        clean_text = self._escape_for_markdown_v2(clean_text)

        return clean_text.strip()

    def _escape_for_markdown_v2(self, text: str) -> str:
        # 1. Экранируем все стандартные спецсимволы (кроме звездочки)
        escape_chars = r'_[]()~`>#+-=|{}.!'
        text = re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

        # 2. Экранируем точки после цифр (списки 1\. 2\.)
        text = re.sub(r'(\d+)\.', r'\1\.', text)

        # 3. Хитрый трюк со звездочками:
        # Нам нужно сохранить **, но экранировать одиночные *.
        # Используем негативный lookbehind и lookahead, чтобы найти * не рядом с другой *
        text = re.sub(r'(?<!\*)\*(?!\*)', r'\*', text)

        return text