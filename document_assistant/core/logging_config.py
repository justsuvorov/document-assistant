"""Единая настройка логирования для обоих процессов (api и worker).

Раньше всё писалось голым ``print()``: без времени, без уровней, без
возможности приглушить шум. В Kubernetes это означало, что время события
видно только с ``kubectl logs --timestamps``, а поднять детализацию без
пересборки образа было нельзя.

Вызывается один раз из точки входа — ``main.py`` (lifespan) и
``document_assistant.worker``.
"""

from __future__ import annotations

import logging
import sys

from document_assistant.core.settings import settings

_configured = False


def setup_logging() -> None:
    """Настроить корневой логгер: stdout, уровень из LOG_LEVEL."""
    global _configured
    if _configured:
        return

    level = logging.getLevelName(settings.log_level.strip().upper())
    if not isinstance(level, int):
        level = logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _configured = True
