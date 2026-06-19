#!/usr/bin/env python3
"""Add departure_date and arrival_date columns to flights.csv."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "flights.csv"


def _minutes_from_hhmm(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def enrich_flights_csv(csv_path: Path) -> int:
    df = pd.read_csv(csv_path)
    if {"departure_date", "arrival_date"}.issubset(df.columns):
        return 0

    base_date = date(2024, 1, 1)
    departure_dates: list[str] = []
    arrival_dates: list[str] = []

    for row in df.itertuples(index=False):
        flight_id = int(row.flight_id)
        departure_date = base_date + timedelta(days=(flight_id - 1) % 365)
        departure_minutes = _minutes_from_hhmm(str(row.departure_time))
        arrival_minutes = _minutes_from_hhmm(str(row.arrival_time))
        arrival_date = (
            departure_date
            if arrival_minutes >= departure_minutes
            else departure_date + timedelta(days=1)
        )
        departure_dates.append(departure_date.isoformat())
        arrival_dates.append(arrival_date.isoformat())

    df.insert(df.columns.get_loc("departure_time"), "departure_date", departure_dates)
    df.insert(df.columns.get_loc("arrival_time"), "arrival_date", arrival_dates)

    column_order = [
        "flight_id",
        "airline",
        "origin",
        "destination",
        "departure_date",
        "departure_time",
        "arrival_date",
        "arrival_time",
        "latency_minutes",
        "status",
    ]
    df[column_order].to_csv(csv_path, index=False)
    return len(df)


def main() -> int:
    parser = argparse.ArgumentParser(description="Add calendar dates to flights.csv")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Path to flights.csv",
    )
    args = parser.parse_args()
    rows = enrich_flights_csv(args.csv.resolve())
    print(f"Updated {args.csv} ({rows:,} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
