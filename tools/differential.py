#!/usr/bin/env python3
"""Compare every book transition and order ledger against an independent oracle.

Run from an installed QueueCraft environment. The reference is standard Python;
it neither calls nor copies the native engine. Deterministic randomized cases
include snapshots, absolute changes/deletes, gaps, ignored updates, recovery,
repeated fills and failed transactions. Real normalized files may be supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

from queuecraft import _native
from queuecraft.reference import BOOK_HEADER, INPUT_HEADER, I64_MAX, Event, Reference, parse_events, replay


def synthetic(seed: int, count: int = 200) -> str:
    randomizer = random.Random(seed)
    events = []
    for index in range(count):
        time = index * 1_000_000
        if index % 37 == 35:
            kind, rows = "G", (("B", 1, 0),)
        elif index % 37 == 36:
            kind, rows = "U", (("A", 110, randomizer.randint(1, 100)),)
        elif index % 37 == 0 or index % 11 == 0:
            kind = "S"
            rows = tuple((side, price, randomizer.randint(1, 1000))
                         for side, prices in (("B", (95, 97, 99)), ("A", (101, 103, 105)))
                         for price in prices)
        else:
            kind = "U"
            side = randomizer.choice(("B", "A"))
            price = randomizer.choice((95, 96, 97, 98, 99) if side == "B" else (101, 102, 103, 104, 105))
            rows = ((side, price, randomizer.choice((0, 1, 10, 100, 1000))),)
        events.append(Event(index, -1, time, kind, rows))
    return INPUT_HEADER + "\n" + "".join(event.csv().split("\n", 1)[1] for event in events)


def _assert_equal(actual, expected, context: str) -> None:
    if actual != expected:
        raise AssertionError(f"{context}\nactual={actual!r}\nexpected={expected!r}")


def compare_case(name: str, text: str, seed: int) -> dict:
    expected_trace = replay(text)
    actual_trace = _native.replay(text)
    _assert_equal(actual_trace, expected_trace, f"{name}: complete no-order trace")
    native, reference = _native.create(), Reference()
    randomizer = random.Random(seed)
    digest = hashlib.sha256()
    attempts = fills = 0
    event_count = 0
    for event in parse_events(text):
        fragment = event.csv()
        actual = _native.apply(native, fragment)
        expected = reference.apply(fragment)
        _assert_equal(actual, expected, f"{name}: event {event.event} full book")
        digest.update(actual.encode())
        event_count += 1
        if not reference.valid:
            continue
        # The schedule and quantities depend only on fixed PRNG state, never on
        # future events, closing prices or favorable hypothetical outcomes.
        if event.event % 3 == 0:
            for _ in range(2):
                side = randomizer.choice(("buy", "sell"))
                quantity = randomizer.randint(1, 300)
                fee = randomizer.choice((0, 1, 1000, 25_000))
                liquidity = randomizer.choice((0, 250_000, 500_000, 1_000_000))
                actual_order = _native.take(native, side, quantity, fee, liquidity)
                expected_order = reference.take(side, quantity, fee, liquidity)
                _assert_equal(actual_order, expected_order, f"{name}: event {event.event} order {attempts}")
                _assert_equal(_native.snapshot(native), reference.snapshot(), f"{name}: post-order recorded depth")
                digest.update(json.dumps(actual_order, sort_keys=True).encode())
                attempts += 1
                fills += len(actual_order["fills"])
    return {
        "case": name, "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "complete_books_compared": event_count, "order_attempts_compared": attempts,
        "fill_records_compared": fills, "transition_sha256": digest.hexdigest(),
        "full_replay_sha256": hashlib.sha256(actual_trace.encode()).hexdigest(),
    }


def error_agreement() -> list[dict]:
    base = Event(0, -1, 0, "S", (("B", 100, 10), ("A", 102, 10))).csv()
    mutations = {
        "truncated_record": base[:-3],
        "missing_final_lf": base[:-1],
        "duplicate_level": base + "0,-1,0,S,A,102,10\n",
        "crossed_snapshot": base.replace(",102,", ",99,"),
        "locked_snapshot": base.replace(",102,", ",100,"),
        "negative_quantity": base.replace(",102,10", ",102,-1"),
        "negative_zero_integer": base.replace(",102,10", ",102,-0"),
        "overflow_integer": base.replace(",102,", f",{I64_MAX + 1},"),
        "inconsistent_snapshot_time": base.replace("0,-1,0,S,A", "0,-1,1,S,A"),
        "unknown_side": base.replace(",A,", ",X,"),
        "extra_field": base.replace(",102,10", ",102,10,extra"),
        "trailing_empty_record": base + "\n",
        "non_ascii_digit": base.replace(",102,", ",１０２,"),
        "quoted_number": base.replace(",102,", ',"102",'),
        "exponent_number": base.replace(",102,", ",1e2,"),
        "invalid_gap": base.replace(",S,", ",G,"),
    }
    reports = []
    for name, text in mutations.items():
        errors = []
        for replay_function in (_native.replay, replay):
            try:
                replay_function(text)
            except (ValueError, OverflowError) as error:
                errors.append(type(error).__name__)
            else:
                raise AssertionError(f"{name}: invalid input accepted by {replay_function}")
        _assert_equal(errors[0], errors[1], f"{name}: error class")
        reports.append({"case": name, "error": errors[0]})
    # The second price overflows after a valid first hypothetical fill. Both
    # implementations must roll back the entire operation, including consumption.
    native, reference = _native.create(), Reference()
    overflow = Event(0, -1, 0, "S", (("B", 1, 5), ("A", 2, 1), ("A", I64_MAX, 2))).csv()
    _native.apply(native, overflow)
    reference.apply(overflow)
    for operation in (lambda: _native.take(native, "buy", 3), lambda: reference.take("buy", 3)):
        try:
            operation()
        except OverflowError:
            pass
        else:
            raise AssertionError("execution overflow accepted")
    _assert_equal(_native.take(native, "buy", 1), reference.take("buy", 1), "post-overflow atomic recovery")
    reports.append({"case": "execution_overflow_atomic_recovery", "error": "OverflowError"})
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="normalized files or directories")
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--events", type=int, default=200)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 100 or not 1 <= args.events <= 10_000:
        parser.error("bounded seeds 1..100 and events 1..10000 required")
    cases = [compare_case(f"synthetic-seed-{seed}", synthetic(seed, args.events), seed) for seed in range(args.seeds)]
    files = []
    for path in args.paths:
        files.extend(sorted(path.glob("*.csv")) if path.is_dir() else [path])
    for index, path in enumerate(files):
        if path.stat().st_size > 64 * 1024**2:
            raise ValueError(f"{path}: input too large")
        cases.append(compare_case(path.name, path.read_text(), index + 1000))
    errors = error_agreement()
    report = {
        "schema_version": 1, "status": "pass", "method": "complete level traces after every event, all fill and cumulative ledger fields after every attempted IOC; independent Python integer oracle",
        "cases": cases, "failure_cases": errors,
        "totals": {key: sum(case[key] for case in cases) for key in ("complete_books_compared", "order_attempts_compared", "fill_records_compared")},
    }
    output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.out:
        with args.out.open("x") as file:
            file.write(output)
    print(json.dumps({"status": report["status"], "cases": len(cases), "failure_cases": len(errors), **report["totals"]}, sort_keys=True))


if __name__ == "__main__":
    main()
