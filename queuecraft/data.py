"""Bounded archive normalization. No settlement labels enter replay events."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from typing import Any

MAX_BYTES = 64 * 1024 * 1024
PRICE_SCALE = 1000  # tick = 0.001 USD per share, exact archive precision
QUANTITY_SCALE = 100  # lot = 0.01 share
MAX_LEVELS = 10000
HEADER = ["event", "exchange_ns", "receive_ns", "kind", "side", "price", "quantity"]


def fixed(value: Any, scale: int) -> int:
    number = Decimal(str(value)) * scale
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError("tick/lot violation")
    result = int(number)
    if result < 0 or result > 2**63 - 1:
        raise ValueError("fixed-point range violation")
    return result


def timestamp_ns(value: datetime | int) -> int:
    if isinstance(value, int):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = value.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def levels(prices: list, sizes: list, side: str) -> list[tuple[str, int, int]]:
    if len(prices) != len(sizes) or not prices or len(prices) > MAX_LEVELS:
        raise ValueError("empty/misaligned/oversized ladder")
    result = [(side, fixed(p, PRICE_SCALE), fixed(q, QUANTITY_SCALE)) for p, q in zip(prices, sizes)]
    if any(p <= 0 or p >= PRICE_SCALE or q <= 0 for _, p, q in result):
        raise ValueError("invalid probability price or size")
    if len({p for _, p, _ in result}) != len(result):
        raise ValueError("duplicate price level")
    return sorted(result, key=lambda row: row[1], reverse=side == "B")


def validate_snapshot(row: dict) -> list[tuple[str, int, int]]:
    bids = levels(row["bid_prices"], row["bid_sizes"], "B")
    asks = levels(row["ask_prices"], row["ask_sizes"], "A")
    if bids[0][1] >= asks[0][1]:
        raise ValueError("crossed or locked book")
    return bids + asks


def normalize(source: Path, destination: Path) -> dict:
    """Freeze all chronological windows, then normalize eligible Up-token windows.

    Invalid snapshots and capture gaps invalidate the book until the next valid
    snapshot. Full windows are retained with exact invalidation reasons. This is
    an integration validity rule, not evidence of exchange-level completeness.
    """
    import duckdb

    if source.stat().st_size > MAX_BYTES:
        raise ValueError("source exceeds 64 MiB")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    destination.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect()
    con.execute("SET memory_limit='512MB'")
    con.execute("SET threads=1")
    # Explicit projection prevents labels, winner and other future fields entering
    # the normalization path. The query itself is part of the audit contract.
    columns = ["market_slug", "token_id", "outcome", "market_end_at", "captured_at", "bid_prices", "bid_sizes", "ask_prices", "ask_sizes"]
    projection = [f"epoch_ns({c}) AS {c}" if c in ("market_end_at", "captured_at") else c for c in columns]
    result = con.execute("SELECT " + ",".join(projection) + " FROM read_parquet(?) WHERE outcome='Up' ORDER BY market_end_at, market_slug, captured_at", [str(source)])
    groups: dict[str, list[dict]] = {}
    for values in result.fetchall():
        row = dict(zip(columns, values))
        groups.setdefault(row["market_slug"], []).append(row)
    if not groups:
        raise ValueError("archive has no Up-token observations")
    ordered = sorted(groups, key=lambda key: (groups[key][0]["market_end_at"], key))
    split = max(1, int(len(ordered) * 0.6))
    report = {"schema_version": 1, "source_sha256": source_hash,
              "split_rule": "all market windows ordered by opening time; first floor(60%) development, remainder confirmation; split BEFORE exclusions",
              "timestamp_semantics": "exchange_ns=-1 unknown; receive_ns is recorded capture time used as modeled observation time, not actual network receive time",
              "price_scale": PRICE_SCALE, "quantity_scale": QUANTITY_SCALE,
              "limitations": ["snapshot-only archive; exchange continuity not observable", "one capture day, correlated short markets, no broad generalization", "uploader license is provenance, not an exchange-rights legal guarantee"],
              "windows": []}
    for index, slug in enumerate(ordered):
        rows = groups[slug]
        entry = {"market_slug": slug, "split": "development" if index < split else "confirmation", "rows": len(rows), "status": "excluded", "reasons": [], "warnings": []}
        times = [timestamp_ns(row["captured_at"]) for row in rows]
        end = timestamp_ns(rows[0]["market_end_at"])
        start = end - 300_000_000_000
        # Some archive rows precede opening; retain them in raw provenance but
        # replay precisely the advertised [opening, settlement) interval.
        selected = [(row, t) for row, t in zip(rows, times) if start <= t < end]
        entry.update(opening_ns=start, settlement_ns=end, preopen_or_postclose_rows=len(rows)-len(selected))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", slug):
            entry["reasons"].append("unsafe market identifier")
        if len({row["token_id"] for row in rows}) != 1 or any(timestamp_ns(row["market_end_at"]) != end for row in rows):
            entry["reasons"].append("inconsistent token or settlement metadata")
        if not selected:
            entry["reasons"].append("no observations in market window")
        else:
            selected_times = [t for _, t in selected]
            if selected_times[0] - start > 5_000_000_000 or end - selected_times[-1] > 5_000_000_000:
                entry["warnings"].append("incomplete interval boundary coverage (>5s)")
            if any(b <= a or b - a > 5_000_000_000 for a, b in zip(selected_times, selected_times[1:])):
                entry["warnings"].append("duplicate timestamps or observation gap >5s")
        prepared = []
        invalid = []
        previous = None
        for row, t in selected:
            if previous is not None and t - previous > 5_000_000_000:
                prepared.append((previous + 5_000_000_001, "G", [("B", 1, 0)]))
                invalid.append({"capture_ns": previous + 5_000_000_001, "reason": "observation gap exceeds 5 seconds"})
            if previous is not None and t <= previous:
                prepared.append((max(t, previous), "G", [("B", 1, 0)]))
                invalid.append({"capture_ns": t, "reason": "duplicate or backward capture timestamp"})
                previous = max(t, previous)
                continue
            try:
                prepared.append((t, "S", validate_snapshot(row)))
            except ValueError as error:
                invalid.append({"capture_ns": t, "reason": str(error)})
                prepared.append((t, "G", [("B", 1, 0)]))
            previous = t
        if invalid:
            entry["warnings"].append("invalid snapshots/gaps retained as G invalidations")
            entry["invalid_snapshots"] = invalid
        if not entry["reasons"]:
            filename = slug + ".csv"
            with (destination / filename).open("x", newline="") as output:
                writer = csv.writer(output, lineterminator="\n")
                writer.writerow(HEADER)
                for event, (t, kind, ladder) in enumerate(prepared):
                    for side, price, size in ladder:
                        writer.writerow([event, -1, t, kind, side, price, size])
            entry.update(status="included", file=filename, events=len(prepared), valid_snapshots=sum(k == "S" for _, k, _ in prepared), invalidations=sum(k == "G" for _, k, _ in prepared), sha256=hashlib.sha256((destination / filename).read_bytes()).hexdigest())
        report["windows"].append(entry)
    report["counts"] = {part: sum(w["status"] == "included" and w["split"] == part for w in report["windows"]) for part in ("development", "confirmation")}
    # Frozen manifest includes every attempted window, including exclusions.
    (destination / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    con.close()
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(normalize(arguments.source, arguments.destination)["counts"]))
