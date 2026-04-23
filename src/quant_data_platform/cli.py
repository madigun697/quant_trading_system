from __future__ import annotations

import argparse
import json

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
    market.add_argument("--stage", default=None)
    market.add_argument("--mode", choices=["recent", "full"], default="full")
    market.add_argument("--start-date", default=None)
    market.add_argument("--end-date", default=None)

    fundamentals = subparsers.add_parser("backfill-fundamentals")
    fundamentals.add_argument("--ciks", nargs="*", default=None)
    fundamentals.add_argument("--cohort", default=None)
    fundamentals.add_argument("--stage", default=None)
    fundamentals.add_argument("--as-of-date", default=None)

    fred = subparsers.add_parser("sync-fred")
    fred.add_argument("--series", nargs="+", required=True)

    daily = subparsers.add_parser("daily-incremental")
    daily.add_argument("--cohort", default=None)
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
            stage=args.stage,
            mode=args.mode,
            start_date=parse_date(args.start_date),
            end_date=parse_date(args.end_date),
        )
    elif args.command == "backfill-fundamentals":
        result = run_fundamental_backfill(
            ciks=args.ciks,
            cohort=args.cohort,
            stage=args.stage,
            as_of_date=parse_date(args.as_of_date),
        )
    elif args.command == "sync-fred":
        result = ingest_fred_series(args.series)
    elif args.command == "daily-incremental":
        result = run_daily_incremental(cohort=args.cohort)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
