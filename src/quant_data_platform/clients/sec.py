from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from quant_data_platform.config import Settings, get_settings
from quant_data_platform.utils import parse_date, parse_datetime

SEC_BASE = "https://data.sec.gov"

COMPANYFACT_FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "ebitda": ("EarningsBeforeInterestTaxesDepreciationAndAmortization",),
    "interest_expense": ("InterestExpenseAndOther", "InterestExpense"),
    "net_income": ("NetIncomeLoss",),
    "basic_eps": ("EarningsPerShareBasic",),
    "diluted_eps": ("EarningsPerShareDiluted",),
    "weighted_average_shares": ("WeightedAverageNumberOfSharesOutstandingBasic", "WeightedAverageNumberOfDilutedSharesOutstanding"),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "total_equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "short_term_debt": ("ShortTermBorrowings", "LongTermDebtCurrent"),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebtAndFinanceLeaseObligations"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpendituresIncurredButNotYetPaid"),
    "dividends_paid": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "share_repurchases": ("PaymentsForRepurchaseOfCommonStock", "CommonStockRepurchasedDuringPeriodValue"),
}


class SECClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.sec_user_agent:
            raise ValueError("SEC_USER_AGENT is required for SEC requests.")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.settings.sec_user_agent})

    def fetch_submissions(self, cik: str) -> dict[str, Any]:
        response = self.session.get(f"{SEC_BASE}/submissions/CIK{cik.zfill(10)}.json", timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_companyfacts(self, cik: str) -> dict[str, Any]:
        response = self.session.get(f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json", timeout=30)
        response.raise_for_status()
        return response.json()


def parse_submission_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "cik": str(payload["cik"]).zfill(10),
        "entity_name": payload.get("name"),
        "primary_ticker": (payload.get("tickers") or [None])[0],
        "tickers": payload.get("tickers") or [],
        "exchanges": payload.get("exchanges") or [],
        "sic": payload.get("sic"),
        "sic_description": payload.get("sicDescription"),
        "submission_json": payload,
    }


def parse_filings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cik = str(payload["cik"]).zfill(10)
    recent = payload.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    acceptance_datetimes = recent.get("acceptanceDateTime", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])
    is_xbrl = recent.get("isXBRL", [])

    rows: list[dict[str, Any]] = []
    for idx, accession in enumerate(accessions):
        filing_date = parse_date(_safe_get(filing_dates, idx))
        accepted_at = parse_datetime(_safe_get(acceptance_datetimes, idx))
        rows.append(
            {
                "cik": cik,
                "accession_number": accession.replace("-", ""),
                "form": _safe_get(forms, idx),
                "filing_date": filing_date,
                "accepted_at": accepted_at,
                "period_end": parse_date(_safe_get(report_dates, idx)),
                "fiscal_year": filing_date.year if filing_date else None,
                "fiscal_period": None,
                "primary_document": _safe_get(primary_docs, idx),
                "filing_href": _build_filing_href(cik, accession, _safe_get(primary_docs, idx)),
                "is_xbrl": bool(_safe_get(is_xbrl, idx)),
                "available_at": accepted_at or (datetime.combine(filing_date, datetime.min.time()) if filing_date else None),
            }
        )
    return rows


def parse_companyfacts(payload: dict[str, Any], filings_by_accession: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cik = str(payload["cik"]).zfill(10)
    facts = payload.get("facts", {})
    rows: list[dict[str, Any]] = []

    for taxonomy, concepts in facts.items():
        for concept_aliases in COMPANYFACT_FIELDS.values():
            for concept in concept_aliases:
                if concept not in concepts:
                    continue
                units = concepts[concept].get("units", {})
                for unit, values in units.items():
                    for fact in values:
                        accession = (fact.get("accn") or "").replace("-", "")
                        filing = filings_by_accession.get(accession, {})
                        period_end = parse_date(fact.get("end"))
                        if period_end is None:
                            continue
                        rows.append(
                            {
                                "cik": cik,
                                "accession_number": accession,
                                "taxonomy": taxonomy,
                                "concept": concept,
                                "unit": unit,
                                "frame": fact.get("frame") or "",
                                "period_start": parse_date(fact.get("start")),
                                "period_end": period_end,
                                "fiscal_year": filing.get("fiscal_year"),
                                "fiscal_period": filing.get("fiscal_period"),
                                "filing_date": filing.get("filing_date"),
                                "accepted_at": filing.get("accepted_at"),
                                "available_at": filing.get("available_at"),
                                "value": fact.get("val"),
                                "raw_fact": fact,
                            }
                        )
    return rows


def _build_filing_href(cik: str, accession: str, document: str | None) -> str | None:
    if not document:
        return None
    accession_no_dash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/{document}"


def _safe_get(values: list[Any], index: int) -> Any:
    if index >= len(values):
        return None
    return values[index]
