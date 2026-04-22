from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from quant_data_platform.config import Settings, get_settings
from quant_data_platform.storage import make_s3_client
from quant_data_platform.utils import dump_json_bytes, sha256_payload


def ensure_bucket(bucket: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    client = make_s3_client(settings)
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def upload_json(bucket: str, object_key: str, payload: Any, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    ensure_bucket(bucket, settings)
    body = dump_json_bytes(payload)
    checksum = sha256_payload(body)
    client = make_s3_client(settings)
    client.put_object(Bucket=bucket, Key=object_key, Body=body, ContentType="application/json")
    return checksum


def upload_bytes(bucket: str, object_key: str, payload: bytes, content_type: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    ensure_bucket(bucket, settings)
    checksum = sha256_payload(payload)
    client = make_s3_client(settings)
    client.put_object(Bucket=bucket, Key=object_key, Body=payload, ContentType=content_type)
    return checksum
