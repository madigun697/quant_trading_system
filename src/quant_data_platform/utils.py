from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def sha256_payload(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def dump_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def parse_date(value: str | None) -> date | None:
    if value in (None, "", "None", "null"):
        return None
    return date.fromisoformat(value)


def parse_datetime(value: str | None) -> datetime | None:
    if value in (None, "", "None", "null"):
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)
