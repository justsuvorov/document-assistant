"""Запуск воркера: python -m document_assistant.worker"""

import asyncio

from document_assistant.worker.runner import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
