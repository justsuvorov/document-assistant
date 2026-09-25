"""Цикл воркера: очередь живёт в таблице sessions, без внешнего брокера.

Redis убран, поэтому задачи забираются прямо из БД. Схема одного оборота:

    claim (атомарный UPDATE) → обработка в потоке → mark_done / mark_error

Параллелизм ограничен ``WORKER_MAX_JOBS``: доменный код синхронный и занимает
поток целиком, поэтому воркер не берёт больше задач, чем может считать.

Запуск: ``python -m document_assistant.worker``
"""

from __future__ import annotations

import asyncio
import logging
import signal

from document_assistant.core.logging_config import setup_logging
from document_assistant.core.settings import settings, warn_if_state_not_shared
from document_assistant.db.engine import (
    async_session_factory,
    dispose_engine,
    init_db,
    masked_database_url,
)
from document_assistant.db.repository import SessionRepository
from document_assistant.storage import storage
from document_assistant.worker.tasks import process_dms_session


logger = logging.getLogger(__name__)

# Реже, чем захват задач: подметать брошенные задачи каждый оборот незачем.
_REAP_EVERY_SECONDS = 60

# «Я жив, очередь пуста» — иначе молчание в логах неотличимо от зависшего
# воркера (например, соединение с БД установлено, но ответа нет).
_HEARTBEAT_EVERY_SECONDS = 60


class Worker:
    def __init__(self) -> None:
        self._stopping = asyncio.Event()
        # Слоты, а не пул потоков: каждая задача уходит в asyncio.to_thread,
        # семафор ограничивает именно количество одновременных обработок.
        self._slots = asyncio.Semaphore(settings.worker_max_jobs)
        self._running: set[asyncio.Task] = set()

    def request_stop(self) -> None:
        if not self._stopping.is_set():
            logger.info("Получен сигнал остановки, новые задачи не берём")
            self._stopping.set()

    async def run(self) -> None:
        logger.info(
            "Конфигурация воркера: "
            f"БД={masked_database_url()}, "
            f"хранилище={settings.storage_dir}, "
            f"модель={settings.qwen_api_url or '<не задан QWEN_API_URL>'}, "
            f"опрос очереди раз в {settings.worker_poll_interval} сек")
        warn_if_state_not_shared()

        try:
            await init_db()
        except Exception as e:
            # Сырой traceback здесь бесполезен тому, кто смотрит kubectl logs:
            # причина почти всегда сетевая (хост/порт БД недоступен из кластера).
            # Выходим с ненулевым кодом — под перезапустится, сигнал не теряется.
            logger.error(
                f"Не удалось подключиться к БД {masked_database_url()}: "
                f"{type(e).__name__}: {e}")
            logger.error(
                "Проверьте доступность хоста и порта БД из кластера "
                "и правильность DATABASE_URL в secret.")
            raise SystemExit(1)

        storage.ensure_root()
        logger.info(
            f"Воркер запущен: каталог {storage.root}, "
            f"параллельно до {settings.worker_max_jobs} задач")

        since_reap = float("inf")  # подмести сразу на старте
        since_heartbeat = 0.0
        polls = 0
        while not self._stopping.is_set():
            if since_reap >= _REAP_EVERY_SECONDS:
                await self._reap_stale()
                since_reap = 0.0

            claimed = await self._claim_and_start()
            polls += 1
            if claimed:
                continue  # очередь не пуста — сразу за следующей

            await self._sleep(settings.worker_poll_interval)
            since_reap += settings.worker_poll_interval
            since_heartbeat += settings.worker_poll_interval

            if since_heartbeat >= _HEARTBEAT_EVERY_SECONDS:
                logger.info(
                    f"Воркер жив: очередь пуста, опросов за последние "
                    f"{int(since_heartbeat)} сек — {polls}")
                since_heartbeat = 0.0
                polls = 0

        await self._drain()

    # ── Шаги цикла ──────────────────────────────────────────────────────────

    async def _claim_and_start(self) -> bool:
        """Взять одну задачу, если есть свободный слот. True — задача взята."""
        if self._slots.locked():
            await self._sleep(settings.worker_poll_interval)
            return False

        # Ошибка БД здесь не должна ронять процесс: у _reap_stale защита уже
        # есть, а этот вызов раньше валил весь воркер в CrashLoopBackOff при
        # любом сетевом сбое — причину приходилось искать в логах предыдущего
        # пода (kubectl logs --previous).
        try:
            async with async_session_factory() as db:
                session = await SessionRepository(db).system_claim_next()
        except Exception as e:
            logger.error(
                f"Не удалось получить задачу из очереди "
                f"(БД {masked_database_url()}): {type(e).__name__}: {e}")
            await self._sleep(settings.worker_poll_interval)
            return False

        if session is None:
            return False

        logger.info(
            f"Воркер взял в обработку сессию {session.id} "
            f"(пользователь {session.user_id}, тип {session.session_type.value})")
        await self._slots.acquire()
        task = asyncio.create_task(self._process(session.id))
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        return True

    async def _process(self, session_id: str) -> None:
        try:
            await asyncio.wait_for(
                process_dms_session({}, session_id),
                timeout=settings.worker_job_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Сессия {session_id}: таймаут обработки")
            await self._mark_error(
                session_id,
                f"Обработка превысила {settings.worker_job_timeout} секунд",
            )
        except Exception as e:
            # process_dms_session ловит ошибки сам; сюда попадает только то,
            # что случилось до или помимо неё — иначе задача осталась бы
            # в processing навсегда.
            logger.exception(f"Сессия {session_id}: {e}")
            await self._mark_error(session_id, f"{type(e).__name__}: {e}")
        finally:
            self._slots.release()

    async def _mark_error(self, session_id: str, message: str) -> None:
        try:
            async with async_session_factory() as db:
                await SessionRepository(db).system_mark_error(session_id, message)
        except Exception as e:
            logger.error(f"Не удалось записать ошибку сессии {session_id}: {e}")

    async def _reap_stale(self) -> None:
        try:
            async with async_session_factory() as db:
                returned = await SessionRepository(db).system_requeue_stale(
                    settings.worker_stale_timeout, settings.worker_max_attempts
                )
            if returned:
                logger.info(f"Возвращено в очередь брошенных задач: {returned}")
        except Exception as e:
            logger.warning(f"Не удалось проверить брошенные задачи: {e}")

    async def _sleep(self, seconds: float) -> None:
        """Пауза, прерываемая сигналом остановки."""
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _drain(self) -> None:
        """Дождаться начатых задач — иначе они остались бы в processing."""
        if self._running:
            logger.info(f"Ждём завершения задач: {len(self._running)}")
            await asyncio.gather(*self._running, return_exceptions=True)
        await dispose_engine()
        logger.info("Воркер остановлен")


async def main() -> None:
    # Идемпотентно: при запуске через python -m document_assistant.worker
    # логирование уже настроено в __main__.py.
    setup_logging()
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            # Windows не поддерживает add_signal_handler — там остановка
            # приходит через KeyboardInterrupt.
            signal.signal(sig, lambda *_: worker.request_stop())
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
