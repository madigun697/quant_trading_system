from __future__ import annotations

import argparse
import json

from quant_data_platform.pipeline import ingest_fred_series, run_daily_incremental, run_fundamental_backfill, run_market_backfill


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quant data platform pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    market = subparsers.add_parser("backfill-market")
    market.add_argument("--symbols", nargs="*", default=None)

    fundamentals = subparsers.add_parser("backfill-fundamentals")
    fundamentals.add_argument("--ciks", nargs="*", default=None)

    fred = subparsers.add_parser("sync-fred")
    fred.add_argument("--series", nargs="+", required=True)

    subparsers.add_parser("daily-incremental")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "backfill-market":
        result = run_market_backfill(symbols=args.symbols)
    elif args.command == "backfill-fundamentals":
        result = run_fundamental_backfill(ciks=args.ciks)
    elif args.command == "sync-fred":
        result = ingest_fred_series(args.series)
    elif args.command == "daily-incremental":
        result = run_daily_incremental()
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps(result, indent=2, default=str))
