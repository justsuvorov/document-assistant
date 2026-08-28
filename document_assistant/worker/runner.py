"""Цикл воркера: очередь живёт в таблице sessions, без внешнего брокера.

Redis убран, поэтому задачи забираются прямо из БД. Схема одного оборота:

    claim (атомарный UPDATE) → обработка в потоке → mark_done / mark_error

Параллелизм ограничен ``WORKER_MAX_JOBS``: доменный код синхронный и занимает
поток целиком, поэтому воркер не берёт больше задач, чем может считать.

Запуск: ``python -m document_assistant.worker``
"""

from __future__ import annotations

import asyncio
import signal
import traceback

from document_assistant.core.settings import settings
from document_assistant.db.engine import async_session_factory, dispose_engine, init_db
from document_assistant.db.repository import SessionRepository
from document_assistant.storage import storage
from document_assistant.worker.tasks import process_dms_session

# Реже, чем захват задач: подметать брошенные задачи каждый оборот незачем.
_REAP_EVERY_SECONDS = 60


class Worker:
    def __init__(self) -> None:
        self._stopping = asyncio.Event()
        # Слоты, а не пул потоков: каждая задача уходит в asyncio.to_thread,
        # семафор ограничивает именно количество одновременных обработок.
        self._slots = asyncio.Semaphore(settings.worker_max_jobs)
        self._running: set[asyncio.Task] = set()

    def request_stop(self) -> None:
        if not self._stopping.is_set():
            print("[INFO] Получен сигнал остановки, новые задачи не берём", flush=True)
            self._stopping.set()

    async def run(self) -> None:
        await init_db()
        storage.ensure_root()
        print(
            f"[INFO] Воркер запущен: каталог {storage.root}, "
            f"параллельно до {settings.worker_max_jobs} задач",
            flush=True,
        )

        since_reap = float("inf")  # подмести сразу на старте
        while not self._stopping.is_set():
            if since_reap >= _REAP_EVERY_SECONDS:
                await self._reap_stale()
                since_reap = 0.0

            claimed = await self._claim_and_start()
            if claimed:
                continue  # очередь не пуста — сразу за следующей

            await self._sleep(settings.worker_poll_interval)
            since_reap += settings.worker_poll_interval

        await self._drain()

    # ── Шаги цикла ──────────────────────────────────────────────────────────

    async def _claim_and_start(self) -> bool:
        """Взять одну задачу, если есть свободный слот. True — задача взята."""
        if self._slots.locked():
            await self._sleep(settings.worker_poll_interval)
            return False

        async with async_session_factory() as db:
            session = await SessionRepository(db).system_claim_next()

        if session is None:
            return False

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
            print(f"[ERROR] Сессия {session_id}: таймаут обработки", flush=True)
            await self._mark_error(
                session_id,
                f"Обработка превысила {settings.worker_job_timeout} секунд",
            )
        except Exception as e:
            # process_dms_session ловит ошибки сам; сюда попадает только то,
            # что случилось до или помимо неё — иначе задача осталась бы
            # в processing навсегда.
            print(f"[ERROR] Сессия {session_id}: {e}", flush=True)
            traceback.print_exc()
            await self._mark_error(session_id, f"{type(e).__name__}: {e}")
        finally:
            self._slots.release()

    async def _mark_error(self, session_id: str, message: str) -> None:
        try:
            async with async_session_factory() as db:
                await SessionRepository(db).system_mark_error(session_id, message)
        except Exception as e:
            print(f"[ERROR] Не удалось записать ошибку сессии {session_id}: {e}", flush=True)

    async def _reap_stale(self) -> None:
        try:
            async with async_session_factory() as db:
                returned = await SessionRepository(db).system_requeue_stale(
                    settings.worker_stale_timeout, settings.worker_max_attempts
                )
            if returned:
                print(f"[INFO] Возвращено в очередь брошенных задач: {returned}", flush=True)
        except Exception as e:
            print(f"[WARN] Не удалось проверить брошенные задачи: {e}", flush=True)

    async def _sleep(self, seconds: float) -> None:
        """Пауза, прерываемая сигналом остановки."""
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _drain(self) -> None:
        """Дождаться начатых задач — иначе они остались бы в processing."""
        if self._running:
            print(f"[INFO] Ждём завершения задач: {len(self._running)}", flush=True)
            await asyncio.gather(*self._running, return_exceptions=True)
        await dispose_engine()
        print("[INFO] Воркер остановлен", flush=True)


async def main() -> None:
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
