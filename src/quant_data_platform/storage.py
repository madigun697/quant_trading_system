from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import boto3
import psycopg
from botocore.client import BaseClient
from psycopg.rows import dict_row

from quant_data_platform.config import Settings, get_settings


def make_s3_client(settings: Settings | None = None) -> BaseClient:
    settings = settings or get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_root_user,
        aws_secret_access_key=settings.minio_root_password,
        region_name=settings.minio_region,
    )


@contextmanager
def postgres_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    settings = settings or get_settings()
    with psycopg.connect(settings.postgres_dsn, row_factory=dict_row) as conn:
        yield conn
