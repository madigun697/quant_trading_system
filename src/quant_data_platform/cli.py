from __future__ import annotations

import argparse
import json

from quant_data_platform.audit import build_mart_coverage_report, render_mart_coverage_report
from quant_data_platform.pipeline import (
    build_liquidity_universe,
    ingest_fred_series,
    run_daily_incremental,
    run_fundamental_backfill,
    run_market_backfill,
)
from quant_data_platform.utils import parse_date


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quant data platform pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    universe = subparsers.add_parser("build-universe")
    universe.add_argument("--cohort", default=None)
    universe.add_argument("--buffer-cohort", default=None)
    universe.add_argument("--buffer-size", type=int, default=None)
    universe.add_argument("--target-size", type=int, default=None)
    universe.add_argument("--discovery-days", type=int, default=None)
    universe.add_argument("--lookback-days", type=int, default=None)

    market = subparsers.add_parser("backfill-market")
    market.add_argument("--symbols", nargs="*", default=None)
    market.add_argument("--cohort", default=None)
    market.add_argument("--full-universe", action="store_true")
    market.add_argument("--stage", default=None)
    market.add_argument("--mode", choices=["recent", "full", "chunked"], default="full")
    market.add_argument("--start-date", default=None)
    market.add_argument("--end-date", default=None)
    market.add_argument("--request-budget", type=int, default=None)
    market.add_argument("--reset-cursor", action="store_true")

    fundamentals = subparsers.add_parser("backfill-fundamentals")
    fundamentals.add_argument("--ciks", nargs="*", default=None)
    fundamentals.add_argument("--cohort", default=None)
    fundamentals.add_argument("--full-universe", action="store_true")
    fundamentals.add_argument("--mode", choices=["full", "chunked"], default="full")
    fundamentals.add_argument("--stage", default=None)
    fundamentals.add_argument("--as-of-date", default=None)
    fundamentals.add_argument("--request-budget", type=int, default=None)
    fundamentals.add_argument("--reset-cursor", action="store_true")

    fred = subparsers.add_parser("sync-fred")
    fred.add_argument("--series", nargs="+", required=True)

    daily = subparsers.add_parser("daily-incremental")
    daily.add_argument("--cohort", default=None)

    audit = subparsers.add_parser("audit-mart-coverage")
    audit.add_argument("--cohort", default=None)
    audit.add_argument("--lookback-months", type=int, default=18)
    audit.add_argument("--format", choices=["text", "json"], default="text")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "build-universe":
        result = build_liquidity_universe(
            cohort=args.cohort,
            buffer_cohort=args.buffer_cohort,
            buffer_size=args.buffer_size,
            target_size=args.target_size,
            discovery_days=args.discovery_days,
            lookback_days=args.lookback_days,
        )
    elif args.command == "backfill-market":
        result = run_market_backfill(
            symbols=args.symbols,
            cohort=args.cohort,
            full_universe=args.full_universe,
            stage=args.stage,
            mode=args.mode,
            start_date=parse_date(args.start_date),
            end_date=parse_date(args.end_date),
            request_budget=args.request_budget,
            reset_cursor=args.reset_cursor,
        )
    elif args.command == "backfill-fundamentals":
        result = run_fundamental_backfill(
            ciks=args.ciks,
            cohort=args.cohort,
            full_universe=args.full_universe,
            mode=args.mode,
            stage=args.stage,
            as_of_date=parse_date(args.as_of_date),
            request_budget=args.request_budget,
            reset_cursor=args.reset_cursor,
        )
    elif args.command == "sync-fred":
        result = ingest_fred_series(args.series)
    elif args.command == "daily-incremental":
        result = run_daily_incremental(cohort=args.cohort)
    elif args.command == "audit-mart-coverage":
        result = build_mart_coverage_report(cohort=args.cohort, lookback_months=args.lookback_months)
        if args.format == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            print(render_mart_coverage_report(result))
        return
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
