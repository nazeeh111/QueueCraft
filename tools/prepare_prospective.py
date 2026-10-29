#!/usr/bin/env python3
"""Freeze and normalize the preregistered 15m archive without policy evaluation."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from queuecraft.data import HEADER, validate_snapshot

NS = 1_000_000_000


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_day(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp // NS, timezone.utc).date().isoformat()


def lower_quartile(values: list[int]) -> int:
    if not values:
        raise ValueError("no eligible development prefixes for depth threshold")
    return sorted(values)[(len(values) - 1) // 4]


def split_for(day: str, plan: dict) -> str:
    if day in plan["development_opening_utc_days"]:
        return "development"
    if day in plan["confirmation_opening_utc_days"]:
        return "confirmation"
    return "excluded_day"


def development_depth_threshold(windows: list[dict]) -> int:
    return lower_quartile([w["prefix_min_top10_lots"] for w in windows if w["status"] == "included" and w["split"] == "development"])


def build_window(rows: list[dict], plan: dict) -> tuple[dict, list]:
    """Build only declared prefixes; terminal validity has an explicit horizon."""
    rows = sorted(rows, key=lambda r: r["captured_at"])
    first = rows[0]
    end = first["market_end_at"]
    opening = end - 900 * NS
    parent_start = opening + plan["parent_start_offset_seconds"] * NS
    recording_end = parent_start + plan["maximum_deadline_seconds"] * NS
    slug = first["market_slug"]
    day = utc_day(opening)
    info = {"market_slug": slug, "coin": first["coin"], "token_id": first["token_id"],
            "opening_ns": opening, "settlement_ns": end, "opening_utc_day": day,
            "parent_start_ns": parent_start, "recording_end_ns": recording_end,
            "split": split_for(day, plan), "full_source_rows": len(rows),
            "full_source_first_capture_ns": rows[0]["captured_at"],
            "full_source_last_capture_ns": rows[-1]["captured_at"],
            "status": "excluded", "reasons": [], "invalidations": [],
            "prefix_spread_ticks": None, "prefix_min_top10_lots": None}
    match = re.fullmatch(r"([a-z]+)-updown-15m-([0-9]+)", slug)
    if not match or int(match[2]) * NS != opening or match[1] != first["coin"]:
        info["reasons"].append("15m identifier/opening metadata mismatch")
    if first["coin"] not in plan["assets"]:
        info["reasons"].append("unsupported asset")
    if any(r["market_end_at"] != end or r["contract_length"] != "15m" or r["coin"] != first["coin"] or r["token_id"] != first["token_id"] for r in rows):
        info["reasons"].append("inconsistent session metadata")
    if info["split"] == "excluded_day":
        info["reasons"].append("opening day outside frozen protocol")
    selected = [r for r in rows if opening <= r["captured_at"] <= recording_end]
    info["normalized_payload_rows"] = len(selected)
    info["unselected_full_source_rows"] = len(rows) - len(selected)
    prepared = []
    watchdog = None
    previous = None
    age = plan["capture_watchdog_ns"]

    def invalidate(t: int, reason: str) -> None:
        prepared.append((t, "G", [("B", 1, 0)]))
        info["invalidations"].append({"observation_ns": t, "reason": reason})

    for row in selected:
        t = row["captured_at"]
        if watchdog is not None and watchdog < t:
            invalidate(watchdog, "capture watchdog exceeded5s")
            watchdog = None
        if previous is not None and t <= previous:
            invalidate(t, "duplicate capture timestamp")
            watchdog = None
        else:
            try:
                ladder = validate_snapshot(row)
            except ValueError as error:
                invalidate(t, str(error))
                watchdog = None
            else:
                prepared.append((t, "S", ladder))
                watchdog = t + age + 1
        previous = t
    if watchdog is not None and watchdog <= recording_end:
        invalidate(watchdog, "terminal capture watchdog exceeded5s")
    if not prepared:
        invalidate(opening, "no captured payload within declared interval")
    prefix = [event for event in prepared if event[0] <= parent_start]
    if not prefix or prefix[-1][1] != "S":
        info["reasons"].append("no valid complete observation at parent start")
    else:
        _, _, ladder = prefix[-1]
        bids = [(p, q) for side, p, q in ladder if side == "B"]
        asks = [(p, q) for side, p, q in ladder if side == "A"]
        info["prefix_spread_ticks"] = asks[0][0] - bids[0][0]
        info["prefix_min_top10_lots"] = min(sum(q for _, q in bids[:10]), sum(q for _, q in asks[:10]))
        info["prefix_source_capture_ns"] = prefix[-1][0]
    info["events"] = len(prepared)
    info["snapshot_events"] = sum(kind == "S" for _, kind, _ in prepared)
    if not info["reasons"]:
        info["status"] = "included"
    return info, prepared


def prepare(source: Path, destination: Path, plan_path: Path, known_path: Path) -> dict:
    import duckdb

    plan = json.loads(plan_path.read_text())
    if source.stat().st_size > plan["source"]["maximum_bytes"]:
        raise ValueError("source exceeds declared size bound")
    if sha(source) != plan["source"]["sha256"]:
        raise ValueError("source hash does not match frozen plan")
    destination.mkdir(exist_ok=False)
    columns = ["market_slug", "coin", "contract_length", "token_id", "market_end_at", "captured_at", "bid_prices", "bid_sizes", "ask_prices", "ask_sizes"]
    projection = [f"epoch_ns({c}) AS {c}" if c in ("market_end_at", "captured_at") else c for c in columns]
    con = duckdb.connect()
    con.execute("SET memory_limit='512MB'")
    con.execute("SET threads=1")
    result = con.execute("SELECT " + ','.join(projection) + " FROM read_parquet(?) WHERE outcome='Up' ORDER BY market_end_at,coin,market_slug,captured_at", [str(source)])
    groups = {}
    for values in result.fetchall():
        row = dict(zip(columns, values))
        groups.setdefault(row["market_slug"], []).append(row)
    con.close()
    if len(groups) > 10000 or sum(map(len, groups.values())) > 1_000_000:
        raise ValueError("archive exceeds declared session/row bounds")
    known_ids = set(json.loads(known_path.read_text())["known_ids"])
    # Split all whole windows BEFORE inspecting their validity or quote regime.
    frozen = [{"market_slug": slug, "coin": rows[0]["coin"], "opening_ns": rows[0]["market_end_at"]-900*NS,
               "opening_utc_day": utc_day(rows[0]["market_end_at"]-900*NS),
               "split": split_for(utc_day(rows[0]["market_end_at"]-900*NS), plan)} for slug, rows in groups.items()]
    with (destination / "day-split.json").open("x") as f:
        json.dump({"plan_sha256": sha(plan_path), "source_sha256": sha(source), "known_ids_sha256": sha(known_path), "windows": frozen}, f, indent=2, sort_keys=True)
        f.write('\n')
    windows, events = [], {}
    for slug, rows in groups.items():
        info, prepared = build_window(rows, plan)
        if slug in known_ids:
            info["reasons"].append("prior known market identifier")
            info["status"] = "excluded"
        windows.append(info)
        events[slug] = prepared
    depth_threshold = development_depth_threshold(windows)
    for window in windows:
        if window["status"] == "included":
            stress_spread = window["prefix_spread_ticks"] > 10
            stress_depth = window["prefix_min_top10_lots"] < depth_threshold
            window.update(condition="stress" if stress_spread or stress_depth else "ordinary", stress_spread=stress_spread, stress_depth=stress_depth)
        # Save every structurally safe window, including eligibility failures.
        if re.fullmatch(r"[a-z]+-updown-15m-[0-9]+", window["market_slug"]):
            path = destination / (window["market_slug"] + ".csv")
            with path.open("x", newline="") as output:
                writer = csv.writer(output, lineterminator='\n')
                writer.writerow(HEADER)
                for i, (t, kind, ladder) in enumerate(events[window["market_slug"]]):
                    writer.writerows((i, -1, t, kind, side, price, quantity) for side, price, quantity in ladder)
            window.update(file=path.name, sha256=sha(path))
    summary = []
    for day in sorted({w["opening_utc_day"] for w in windows}):
        selected = [w for w in windows if w["opening_utc_day"] == day]
        summary.append({"opening_utc_day": day, "split": selected[0]["split"], "attempted_windows": len(selected),
                        "included": sum(w["status"] == "included" for w in selected),
                        "ordinary": sum(w.get("condition") == "ordinary" for w in selected),
                        "stress": sum(w.get("condition") == "stress" for w in selected),
                        "excluded_reasons": dict(Counter(reason for w in selected for reason in w["reasons"]))})
    manifest = {"version": plan["version"], "no_policy_outcomes_evaluated": True, "plan_sha256": sha(plan_path),
                "source_sha256": sha(source), "day_split_sha256": sha(destination / "day-split.json"),
                "depth_threshold_lots": depth_threshold, "depth_threshold_method": plan["stress_proxy"]["depth_threshold"],
                "price_scale": 1000, "quantity_scale": 100, "windows": windows, "day_summary": summary,
                "prior_known_ids_sha256": sha(known_path), "prior_overlap_count": sum(w["market_slug"] in known_ids for w in windows),
                "limitations": ["short correlated markets across four capture days; random sampled windows", "prefix quote/depth proxies are not externally observed market-wide stress", "capture time used as modeled observation time; exchange_ns unknown", "explicit recording horizon uses publisher-declared whole-session coverage; watchdog conservatively invalidates sparse snapshots", "original 5m study and failed ordinary coverage retained; prospective protocol is distinct"]}
    with (destination / "manifest.json").open("x") as output:
        json.dump(manifest, output, indent=2, sort_keys=True)
        output.write('\n')
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/15m-archive/updown_15m.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/prospective-v2/sessions"))
    parser.add_argument("--plan", type=Path, default=Path("docs/PROSPECTIVE_PLAN.json"))
    parser.add_argument("--known-ids", type=Path, default=Path("data/15m-archive/prior_known_ids.json"))
    args = parser.parse_args()
    report = prepare(args.source, args.output, args.plan, args.known_ids)
    print(json.dumps({"depth_threshold_lots": report["depth_threshold_lots"], "day_summary": report["day_summary"], "prior_overlap_count": report["prior_overlap_count"]}, indent=2))
