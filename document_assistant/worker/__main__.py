"""Запуск воркера: python -m document_assistant.worker"""

import asyncio

from document_assistant.core.logging_config import setup_logging
from document_assistant.worker.runner import main

if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
