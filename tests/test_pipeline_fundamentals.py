from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from quant_data_platform.pipeline import run_fundamental_backfill


class _DummyConn:
    def commit(self) -> None:
        return None


@contextmanager
def _fake_postgres_connection(_settings):
    yield _DummyConn()


def test_run_fundamental_backfill_chunked_uses_watermark(monkeypatch) -> None:
    watermark_updates: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_sec_ticker_reference", lambda settings=None: {"reference_rows": 10})
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_universe_ciks",
        lambda conn, cohort, snapshot_as_of=None, limit=None: ["0001", "0002", "0003", "0004"],
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.get_ingestion_watermark",
        lambda conn, source_name, resource_name: "2",
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.upsert_ingestion_watermark",
        lambda conn, source_name, resource_name, cursor_value: watermark_updates.append(
            (source_name, resource_name, cursor_value)
        ),
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.ingest_sec_ciks",
        lambda ciks, settings=None: {"filings": len(list(ciks)), "facts": len(list(ciks)) * 2},
    )

    result = run_fundamental_backfill(
        cohort="us_liquidity_700_v1",
        mode="chunked",
        request_budget=2,
        as_of_date=date(2026, 4, 23),
    )

    assert result["reference_rows"] == 10
    assert result["cik_count"] == 2
    assert result["processed_offset_start"] == 2
    assert result["processed_offset_end"] == 4
    assert result["remaining_ciks"] == 0
    assert result["filings"] == 2
    assert result["facts"] == 4
    assert watermark_updates == [("sec", "sec_companyfacts:us_liquidity_700_v1", "4")]


def test_run_fundamental_backfill_full_uses_all_ciks(monkeypatch) -> None:
    captured: list[str] = []

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_sec_ticker_reference", lambda settings=None: {"reference_rows": 10})
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_universe_ciks",
        lambda conn, cohort, snapshot_as_of=None, limit=None: ["0001", "0002", "0003"],
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.ingest_sec_ciks",
        lambda ciks, settings=None: captured.extend(ciks) or {"filings": len(captured), "facts": len(captured) * 3},
    )

    result = run_fundamental_backfill(cohort="us_liquidity_700_v1", as_of_date=date(2026, 4, 23))

    assert captured == ["0001", "0002", "0003"]
    assert result["reference_rows"] == 10
    assert result["cik_count"] == 3
    assert result["filings"] == 3
    assert result["facts"] == 9
