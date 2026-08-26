"""S3-совместимое хранилище (AWS S3 / MinIO / Ceph RGW).

Доменная логика (``DataParser``, ``ReportExport``, ``AIAssistantService``)
работает исключительно с локальными путями и не знает про S3. Поэтому здесь
только три операции — залить, скачать во временный файл, выдать presigned URL,
плюс контекст-менеджер рабочей папки, внутри которой доменный код
отрабатывает ровно как раньше.

Важно: ``ReportExport`` кладёт результат рядом с исходным файлом
(``request.xlsx`` → ``request_ответ.xlsx``), туда же ложатся
``*_llm_debug.md`` и ``*_llm_output.json``. Поэтому вход скачивается в
отдельную временную папку под своим настоящим именем — все выходные
артефакты появляются в той же папке и оттуда забираются в S3.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from document_assistant.core.settings import settings


class S3Storage:
    """Тонкая обёртка над boto3. Один экземпляр на процесс."""

    def __init__(self) -> None:
        self._client = None

    @property
    def bucket(self) -> str:
        return settings.s3_bucket

    @property
    def client(self):
        """Ленивый клиент — чтобы импорт модуля не требовал живого S3."""
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url or None,
                aws_access_key_id=settings.s3_access_key or None,
                aws_secret_access_key=settings.s3_secret_key.get_secret_value() or None,
                region_name=settings.s3_region,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"},
                ),
            )
        return self._client

    def ensure_bucket(self) -> None:
        """Создать бакет, если его нет. Для локального MinIO при старте."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code not in ("404", "NoSuchBucket", "NotFound"):
                raise
            self.client.create_bucket(Bucket=self.bucket)
            print(f"[INFO] S3: создан бакет {self.bucket}", flush=True)

    def upload_file(self, local_path: str | Path, key: str) -> None:
        self.client.upload_file(str(local_path), self.bucket, key)

    def download_to_tmp(self, key: str, dest_dir: str | Path | None = None) -> Path:
        """Скачать объект в локальный файл, сохранив исходное имя.

        Без ``dest_dir`` создаётся новая временная папка — вызывающий обязан
        удалить её сам (или использовать ``workspace()``).
        """
        directory = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="da-"))
        directory.mkdir(parents=True, exist_ok=True)
        local_path = directory / Path(key).name
        self.client.download_file(self.bucket, key, str(local_path))
        return local_path

    def presigned_url(self, key: str, expires: int | None = None) -> str:
        """Ссылка на скачивание с ограниченным сроком жизни.

        Бакет всегда приватный — это единственный способ отдать файл клиенту.
        ``ResponseContentDisposition`` заставляет браузер скачать файл под
        нормальным именем, а не под UUID-путём.
        """
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{Path(key).name}"',
            },
            ExpiresIn=expires if expires is not None else settings.s3_presign_expires,
        )

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete_prefix(self, prefix: str) -> None:
        """Удалить всё под префиксом (например, всю сессию)."""
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})


storage = S3Storage()


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


# ── Модульные шорткаты (сигнатуры из ТЗ) ────────────────────────────────────

def upload_file(local_path: str | Path, key: str) -> None:
    storage.upload_file(local_path, key)


def download_to_tmp(key: str, dest_dir: str | Path | None = None) -> Path:
    return storage.download_to_tmp(key, dest_dir)


def presigned_url(key: str, expires: int = 3600) -> str:
    return storage.presigned_url(key, expires)


@contextmanager
def workspace(prefix: str = "da-") -> Iterator[Path]:
    """Временная папка, удаляемая в любом случае.

    Внутри неё доменный код работает с обычными путями — файлы не задерживаются
    на диске контейнера дольше одной задачи.
    """
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
