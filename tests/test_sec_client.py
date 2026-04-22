from __future__ import annotations

import json

from quant_data_platform.clients.sec import parse_companyfacts, parse_filings, parse_submission_summary
from tests.conftest import FIXTURE_DIR


def test_parse_submission_summary_and_filings() -> None:
    payload = json.loads((FIXTURE_DIR / "sec_submissions.json").read_text())
    summary = parse_submission_summary(payload)
    filings = parse_filings(payload)
    assert summary["cik"] == "0000051143"
    assert filings[0]["accession_number"] == "000005114324000012"


def test_parse_companyfacts() -> None:
    submissions = json.loads((FIXTURE_DIR / "sec_submissions.json").read_text())
    filing_rows = parse_filings(submissions)
    companyfacts = json.loads((FIXTURE_DIR / "sec_companyfacts.json").read_text())
    rows = parse_companyfacts(companyfacts, {row["accession_number"]: row for row in filing_rows})
    assert rows
    assert any(row["concept"] == "Revenues" for row in rows)
