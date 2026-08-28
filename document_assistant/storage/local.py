"""Файловое хранилище на диске сервера.

Раньше здесь был S3; devops выбрал локальный диск, поэтому «ключ» теперь
просто относительный путь внутри ``STORAGE_DIR``:

    {storage_dir}/{user_id}/{session_id}/input/Запрос.xlsx
    {storage_dir}/{user_id}/{session_id}/output/Запрос_ответ.xlsx

Интерфейс намеренно сохранён ключ-ориентированным (``upload_file``,
``download_to_tmp``), а не «дай мне путь»: доменный код и воркер продолжают
работать с временными папками, а вся привязка к дисковой раскладке остаётся
в одном месте. Если хранилище когда-нибудь снова станет внешним, меняется
только этот модуль.

Каталог должен быть общим для api и воркера — в compose это один том.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from document_assistant.core.settings import settings


class UnsafeKeyError(ValueError):
    """Ключ ведёт за пределы каталога хранилища."""


class LocalStorage:
    """Тонкая обёртка над файловой системой. Один экземпляр на процесс."""

    @property
    def root(self) -> Path:
        return Path(settings.storage_dir).resolve()

    # ── Безопасность путей ──────────────────────────────────────────────────

    def resolve(self, key: str) -> Path:
        """Ключ → абсолютный путь, с проверкой выхода за пределы каталога.

        Ключи собираются из имён загруженных файлов, поэтому путь обязан
        проверяться здесь, а не только на входе: ``../`` в ключе иначе дал бы
        чтение и запись в любом месте диска.
        """
        if not key or key.startswith(("/", "\\")) or ":" in key.replace("://", ""):
            raise UnsafeKeyError(f"Недопустимый ключ: {key!r}")
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise UnsafeKeyError(f"Ключ выходит за пределы хранилища: {key!r}")
        return candidate

    # ── Операции ────────────────────────────────────────────────────────────

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def upload_file(self, local_path: str | Path, key: str) -> None:
        """Положить файл в хранилище под ключом (перезаписывая существующий)."""
        dest = self.resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(local_path), dest)

    def download_to_tmp(self, key: str, dest_dir: str | Path | None = None) -> Path:
        """Скопировать объект в рабочую папку, сохранив исходное имя.

        Копия, а не ссылка на оригинал: доменный код складывает артефакты
        рядом с исходным файлом, и работать он должен во временной папке,
        не засоряя каталог сессии.
        """
        source = self.resolve(key)
        if not source.is_file():
            raise FileNotFoundError(f"В хранилище нет объекта {key}")
        directory = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="da-"))
        directory.mkdir(parents=True, exist_ok=True)
        local_path = directory / source.name
        shutil.copy2(source, local_path)
        return local_path

    def path_for_download(self, key: str) -> Path:
        """Путь для отдачи файла клиенту. Отдаёт только существующий файл."""
        path = self.resolve(key)
        if not path.is_file():
            raise FileNotFoundError(f"В хранилище нет объекта {key}")
        return path

    def exists(self, key: str) -> bool:
        try:
            return self.resolve(key).is_file()
        except UnsafeKeyError:
            return False

    def delete_prefix(self, prefix: str) -> None:
        """Удалить всё под префиксом (например, всю сессию)."""
        target = self.resolve(prefix)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.is_file():
            target.unlink(missing_ok=True)


storage = LocalStorage()


# ── Схема ключей ────────────────────────────────────────────────────────────
# Префикс всегда начинается с user_id — принадлежность файла видна прямо в
# ключе, что делает проверку доступа независимой от состояния БД.

def session_prefix(user_id: str, session_id: str) -> str:
    return f"{user_id}/{session_id}"


def input_key(user_id: str, session_id: str, filename: str) -> str:
    return f"{session_prefix(user_id, session_id)}/input/{Path(filename).name}"


def output_key(user_id: str, session_id: str, filename: str) -> str:
    return f"{session_prefix(user_id, session_id)}/output/{Path(filename).name}"


def key_belongs_to(key: str, user_id: str) -> bool:
    """Ключ принадлежит пользователю, если начинается с его user_id."""
    return key.startswith(f"{user_id}/")


# ── Модульные шорткаты ──────────────────────────────────────────────────────

def upload_file(local_path: str | Path, key: str) -> None:
    storage.upload_file(local_path, key)


def download_to_tmp(key: str, dest_dir: str | Path | None = None) -> Path:
    return storage.download_to_tmp(key, dest_dir)


@contextmanager
def workspace(prefix: str = "da-") -> Iterator[Path]:
    """Временная папка, удаляемая в любом случае.

    Внутри неё доменный код работает с обычными путями — промежуточные файлы
    не задерживаются в каталоге хранилища.
    """
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
