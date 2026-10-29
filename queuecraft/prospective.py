"""Frozen prospective study with development-only work calibration.

The recorder's declared end is independent of event payloads. Evaluation
benchmarks never enter policy observations. Every parent configuration is
accounted for as an execution or a named, matched exclusion.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import asdict
import hashlib
from itertools import combinations, product
import json
import math
import platform
from pathlib import Path
import random
import statistics
import time
from typing import Sequence

from .policies import POLICIES, PlanningConfig, RecedingHorizon
from .reconcile import reconcile_many
from .sdk import Book, Event, HEADER, Intent, Observation, Scenario, events_from_csv, run

NS = 1_000_000_000
PRODUCTION_CALIBRATION_SAMPLES = 5_000
PRODUCTION_BOOTSTRAP_SAMPLES = 1_000
OUTPUT_LIMIT = 1_073_741_824
DECISION_BUDGET_NS = NS
MAX_FILE_BYTES = 64 * 1024**2


def _read_bytes(path: Path, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    with path.open("rb") as source:
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("input exceeds byte bound during read")
    return content


def _sha(path: Path, max_bytes: int = MAX_FILE_BYTES) -> str:
    # Count actual bytes, not a preceding stat that can race with a growing file.
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(min(65536, max_bytes - total + 1)):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("input exceeds byte bound during hashing")
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes() -> dict[str, str]:
    return {path.name: _sha(path) for path in sorted(Path(__file__).parent.iterdir())
            if path.suffix in {".py", ".sql"} or path.name == "native-source.json"}


def _native_hash() -> str:
    from . import _native
    return _sha(Path(_native.__file__))


def _check_frozen(registration: dict, sessions: Path, plan_path: Path, *,
                  session_name: str | None = None, complete: bool = True, raw_archive_path: Path | None = None) -> None:
    if _source_hashes() != registration["source_hashes"] or _native_hash() != registration["native_binary_sha256"]:
        raise ValueError("source changed after registration; retain partial study and use a new destination")
    if _sha(plan_path) != registration["plan_sha256"] or _sha(sessions / "manifest.json") != registration["manifest_sha256"]:
        raise ValueError("plan or manifest changed after registration")
    selected = registration["session_hashes"] if complete else ({session_name: registration["session_hashes"][session_name]} if session_name else {})
    for name, digest in selected.items():
        if _sha(sessions / name) != digest:
            raise ValueError(f"frozen input changed: {name}")
    raw_name = registration.get("raw_archive_file")
    if complete and raw_name:
        raw = Path(raw_archive_path) if raw_archive_path is not None else sessions.parent / "raw" / raw_name
        if _sha(raw, registration["raw_archive_max_bytes"]) != registration["raw_archive_sha256"]:
            raise ValueError("raw archive changed after registration")


def _planning_config(plan: dict) -> PlanningConfig:
    family = plan["horizon_planning_family"]
    shocks = tuple(int(value * 1_000_000) for value in family["drift_spread_multipliers"])
    if any(value * 1_000_000 != shock for value, shock in zip(family["drift_spread_multipliers"], shocks)):
        raise ValueError("planning shocks must have exact millionth-spread units")
    quanta = family["cumulative_target_quarters"]
    if quanta != list(range(len(quanta))):
        raise ValueError("planning cumulative targets must be contiguous integer quanta")
    return PlanningConfig(tuple(family["latencies_ns"]), tuple(family["liquidity_ppm"]), shocks,
                          family["stages"], quanta[-1], family["maximum_projected_levels"], family["maximum_price_ticks"])


def _policy(name: str, config: PlanningConfig):
    if name == "horizon":
        return RecedingHorizon(config)
    return POLICIES[name]()


def _read_events(path: Path, before_ns: int | None = None) -> tuple[Event, ...]:
    if before_ns is None:
        return events_from_csv(_read_bytes(path, MAX_FILE_BYTES).decode("ascii"))
    # Calibration parses only original prefix bytes. Each readline is bounded
    # too: a growing or unterminated row cannot allocate an unbounded string.
    with path.open("rb") as source:
        header = source.readline(len(HEADER.encode("ascii")) + 1)
        if header != HEADER.encode("ascii"):
            raise ValueError("invalid normalized header")
        selected = [header]
        total = len(header)
        while line := source.readline(MAX_FILE_BYTES - total + 1):
            total += len(line)
            if total > MAX_FILE_BYTES:
                raise ValueError("prefix exceeds byte bound during read")
            fields = line.split(b",")
            if len(fields) != 7:
                raise ValueError("invalid normalized row")
            if int(fields[2]) > before_ns:
                break
            selected.append(line)
    return events_from_csv(b"".join(selected).decode("ascii"))


def _prefix(window: dict, sessions: Path) -> tuple[tuple[Event, ...], tuple, tuple, int, int, int]:
    events = _read_events(sessions / window["file"], window["parent_start_ns"])
    book = Book()
    for event in events:
        book.apply(event)
    rows = list(csv.DictReader(book.trace().splitlines()))
    if not rows or rows[0]["valid"] != "1":
        raise ValueError("prepared included window has invalid parent prefix")
    bids = tuple(sorted(((int(row["price"]), int(row["quantity"])) for row in rows if row["side"] == "B"), reverse=True))
    asks = tuple(sorted((int(row["price"]), int(row["quantity"])) for row in rows if row["side"] == "A"))
    if not bids or not asks:
        raise ValueError("prepared included window has no two-sided parent quote")
    depth = min(sum(q for _, q in bids[:10]), sum(q for _, q in asks[:10]))
    if depth != window["prefix_min_top10_lots"] or asks[0][0] - bids[0][0] != window["prefix_spread_ticks"]:
        raise ValueError("prepared prefix metadata differs from native reconstruction")
    return events, bids, asks, bids[0][0] + asks[0][0], depth, int(rows[0]["receive_ns"])


def _nearest(values: Sequence[int | float], probability: float):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def _calibration_inputs(windows: list[dict], sessions: Path, plan: dict) -> tuple[list[Observation], list[dict]]:
    selected = sorted((window for window in windows if window["status"] == "included" and window["split"] == "development"),
                      key=lambda window: (window["parent_start_ns"], window["coin"], window["market_slug"]))[:32]
    if not selected:
        raise ValueError("no eligible development prefixes for policy calibration")
    observations = []
    prefixes = []
    for window in selected:
        events, bids, asks, _, _, receive_ns = _prefix(window, sessions)
        start = window["parent_start_ns"]
        intent = Intent("buy", 100, start, start + 30 * NS, penalty_ticks=plan["unfilled_penalty_ticks"], max_quantity=10_000)
        observations.append(Observation(start, events[-1].exchange_ns, receive_ns, events[-1].index,
                                        bids, asks, True, 0, 100, 0, intent, Scenario(max_staleness_ns=plan["capture_watchdog_ns"])))
        prefixes.append({"session": window["market_slug"], "day": window["opening_utc_day"],
                         "prefix_sha256": hashlib.sha256("".join(event.csv() for event in events).encode()).hexdigest()})
    return observations, prefixes


def _calibrate(windows: list[dict], sessions: Path, plan: dict, config: PlanningConfig, samples: int) -> dict:
    observations, prefixes = _calibration_inputs(windows, sessions, plan)
    measured = {}
    for name in plan["policies"]:
        for observation in observations:
            _policy(name, config).decide(observation)
        durations = []
        for index in range(samples):
            observation = observations[index % len(observations)]
            before = time.perf_counter_ns()
            _policy(name, config).decide(observation)
            durations.append(time.perf_counter_ns() - before)
        p99 = _nearest(durations, .99)
        measured[name] = {"samples": samples, "raw_ns": durations, "p50_ns": _nearest(durations, .5),
                          "p95_ns": _nearest(durations, .95), "p99_ns": p99,
                          "declared_duration_ns": max(1_000_000, ((p99 + 999_999) // 1_000_000) * 1_000_000)}
    return {"method": "cold constructor+decide; balanced cyclic development prefixes; no fills/future data",
            "samples_per_policy": samples, "warmups_per_prefix_per_policy": 1, "clock": "time.perf_counter_ns",
            "prefixes": prefixes, "policies": measured, "shared_decision_budget_ns": DECISION_BUDGET_NS,
            "limits": ["empirical local desktop work sensitivity, not calibrated latency",
                       "no confirmation timings or policy outcomes used", "no p999 inference"]}


def _validate_calibration(calibration: dict, identity: dict, windows: list[dict], sessions: Path,
                          plan: dict, samples: int) -> None:
    if calibration.get("identity") != identity:
        raise ValueError("calibration source, plan, data or planning identity differs")
    _, prefixes = _calibration_inputs(windows, sessions, plan)
    if calibration.get("prefixes") != prefixes:
        raise ValueError("calibration did not use the declared development prefixes")
    if calibration.get("shared_decision_budget_ns") != DECISION_BUDGET_NS or calibration.get("warmups_per_prefix_per_policy") != 1:
        raise ValueError("calibration changed the common budget or warmup rule")
    if calibration.get("samples_per_policy") != samples or set(calibration.get("policies", {})) != set(plan["policies"]):
        raise ValueError("calibration policies or sample counts differ")
    environment = calibration.get("measurement_environment", {})
    native_hash = environment.get("native_binary_sha256", "")
    if calibration.get("clock") != "time.perf_counter_ns" or not all(isinstance(environment.get(key), str) and environment[key] for key in ("platform", "python")) or len(native_hash) != 64 or any(char not in "0123456789abcdef" for char in native_hash):
        raise ValueError("calibration lacks measurement provenance")
    for item in calibration["policies"].values():
        values = item.get("raw_ns", [])
        if len(values) != samples or any(type(value) is not int or value < 0 for value in values) or item.get("samples") != samples:
            raise ValueError("invalid calibration timing samples")
        for label, quantile in (("p50_ns", .5), ("p95_ns", .95), ("p99_ns", .99)):
            if item.get(label) != _nearest(values, quantile):
                raise ValueError("calibration quantile differs from retained samples")
        expected = max(1_000_000, ((item["p99_ns"] + 999_999) // 1_000_000) * 1_000_000)
        if item.get("declared_duration_ns") != expected:
            raise ValueError("calibration duration violates fixed rounding rule")


def _summary(rows: list[dict], dimensions: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[name] for name in dimensions)].append(row)
    result = []
    for key, group in sorted(groups.items()):
        costs = [row["cost_ticks_per_lot"] for row in group]
        result.append(dict(zip(dimensions, key)) | {
            "windows": len({row["session"] for row in group}), "trials": len(group),
            "mean_cost": statistics.fmean(costs), "p95_cost": _nearest(costs, .95),
            "mean_completion": statistics.fmean(row["completion"] for row in group),
            "fees": sum(row["fees"] for row in group), "unfilled": sum(row["unfilled"] for row in group),
            "sql_transitions": sum(row["sql_transitions"] for row in group),
            "sql_fills": sum(row["sql_fills"] for row in group)})
    return result


def _bootstrap(values: tuple[float, ...], samples: int) -> list[float] | None:
    if not values:
        return None
    if min(values) == max(values):
        return [values[0], values[0]]
    rng = random.Random(1234)
    means = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples)]
    return [_nearest(means, .025), _nearest(means, .975)]


def _stability(rows: list[dict], plan: dict, samples: int) -> list[dict]:
    indexed = {(row["session"], row["policy"], row["scenario"], row["side"], row["size"], row["deadline_s"]): row for row in rows}
    window_info = {row["session"]: row for row in rows}
    worlds = [(spec["name"], mode) for spec, mode in product(plan["scenarios"], plan["policy_compute_sensitivity"]["modes"])]
    cache = {}
    result = []
    for split, condition, pair, side, size, deadline in product(
            ("development", "confirmation"), ("all", "ordinary", "stress"), combinations(plan["policies"], 2),
            plan["sides"], plan["quantities_lots"], plan["deadlines_seconds"]):
        a, b = pair
        eligible_sessions = sorted(name for name, info in window_info.items() if info["split"] == split and (condition == "all" or info["condition"] == condition))
        # Use the SAME paired windows in every assumption/compute world. A
        # composition change must not be mistaken for an assumption reversal.
        sessions = [session for session in eligible_sessions if all(
            (session, policy, base + "/" + mode, side, size, deadline) in indexed
            for base, mode in worlds for policy in (a, b))]
        scenarios = []
        for base, mode in worlds:
            name = base + "/" + mode
            differences = []
            by_day: dict[str, list[float]] = defaultdict(list)
            for session in sessions:
                x = indexed.get((session, a, name, side, size, deadline))
                y = indexed.get((session, b, name, side, size, deadline))
                if x is not None and y is not None:
                    difference = x["cost_ticks_per_lot"] - y["cost_ticks_per_lot"]
                    differences.append(difference)
                    by_day[x["opening_day"]].append(difference)
            values = tuple(differences)
            if values not in cache:
                cache[values] = _bootstrap(values, samples)
            scenarios.append({"scenario": name, "execution_scenario": base, "compute_mode": mode,
                              "windows": len(values), "days": len(by_day),
                              "difference_a_minus_b": statistics.fmean(values) if values else None,
                              "window_bootstrap95": cache[values],
                              "day_means": {day: statistics.fmean(items) for day, items in sorted(by_day.items())},
                              "day_interval": None,
                              "uncertainty_scope": "conditional correlated-window bootstrap; no independent-day interval"})
        means = [item["difference_a_minus_b"] for item in scenarios if item["difference_a_minus_b"] is not None]
        reversal = bool(means) and min(means) < 0 < max(means)
        unresolved = any(item["window_bootstrap95"] is None or item["window_bootstrap95"][0] <= 0 <= item["window_bootstrap95"][1] for item in scenarios)
        result.append({"split": split, "condition": condition, "a": a, "b": b, "side": side,
                       "size": size, "deadline_s": deadline, "status": "unresolved" if unresolved else "reversal" if reversal else "stable",
                       "mean_sign_reversal": reversal, "common_windows": len(sessions),
                       "unmatched_windows": [name for name in eligible_sessions if name not in sessions], "scenarios": scenarios})
    return result


def study(sessions: Path, plan_path: Path, output: Path, *, calibration_path: Path | None = None, raw_archive_path: Path | None = None, _test_settings: dict | None = None) -> dict:
    """Execute one exclusive study; incomplete runs remain explicit artifacts.

    Tiny calibration/bootstrap overrides are accepted only for plans explicitly
    marked ``test_only``. Production always retains all windows and uses5000
    measured decisions per policy and1000 bootstrap resamples.
    """
    sessions, plan_path, output = Path(sessions), Path(plan_path), Path(output)
    plan_bytes = _read_bytes(plan_path)
    plan = json.loads(plan_bytes)
    if _test_settings is not None and plan.get("test_only") is not True:
        raise ValueError("test overrides require an explicitly test_only plan")
    options = _test_settings or {}
    if set(options) - {"calibration_samples", "bootstrap_samples", "max_output_bytes"}:
        raise ValueError("unknown test-only setting")
    calibration_samples = options.get("calibration_samples", PRODUCTION_CALIBRATION_SAMPLES)
    bootstrap_samples = options.get("bootstrap_samples", PRODUCTION_BOOTSTRAP_SAMPLES)
    output_limit = options.get("max_output_bytes", OUTPUT_LIMIT)
    if any(type(value) is not int or value < 1 for value in (calibration_samples, bootstrap_samples, output_limit)):
        raise ValueError("study settings must be positive integers")
    modes = plan["policy_compute_sensitivity"]["modes"]
    if modes != ["zero_compute_baseline", "measured_development_compute"]:
        raise ValueError("unsupported compute sensitivity protocol")
    if len(set(plan["policies"])) != len(plan["policies"]) or any(name not in POLICIES for name in plan["policies"]):
        raise ValueError("unknown or duplicate registered policy")
    config = _planning_config(plan)
    manifest_bytes = _read_bytes(sessions / "manifest.json")
    manifest = json.loads(manifest_bytes)
    windows = sorted(manifest["windows"], key=lambda window: (window.get("opening_ns", 2**63-1), window["coin"], window["market_slug"]))
    if plan.get("test_only") is not True and plan.get("resource_limits", {}).get("retain_all_265_window_attempts") is True and len(windows) != 265:
        raise ValueError("registered population requires all265 window attempts")
    if len({window["market_slug"] for window in windows}) != len(windows):
        raise ValueError("duplicate session identifier")
    if manifest["source_sha256"] != plan["source"]["sha256"]:
        raise ValueError("archive identity differs from registered source")
    for window in windows:
        day = window["opening_utc_day"]
        expected = "development" if day in plan["development_opening_utc_days"] else "confirmation" if day in plan["confirmation_opening_utc_days"] else "excluded_day"
        if window["split"] != expected:
            raise ValueError("window violates frozen whole-day split")
    if max(plan["development_opening_utc_days"]) >= min(plan["confirmation_opening_utc_days"]):
        raise ValueError("development must strictly precede confirmation opening days")
    depths = sorted(window["prefix_min_top10_lots"] for window in windows
                    if window["status"] == "included" and window["split"] == "development")
    if not depths or manifest["depth_threshold_lots"] != depths[(len(depths)-1)//4]:
        raise ValueError("development-only depth threshold differs")
    for window in windows:
        if window["status"] != "included":
            continue
        if window["parent_start_ns"] != window["opening_ns"] + plan["parent_start_offset_seconds"] * NS:
            raise ValueError("parent start differs from registered offset")
        if window["recording_end_ns"] != window["parent_start_ns"] + plan["maximum_deadline_seconds"] * NS:
            raise ValueError("recording end differs from declared interval")
        if window["settlement_ns"] != window["opening_ns"] + 900 * NS or window["recording_end_ns"] > window["settlement_ns"]:
            raise ValueError("recording interval exceeds15minute source lifetime")
        expected_condition = "stress" if window["prefix_spread_ticks"] > 10 or window["prefix_min_top10_lots"] < manifest["depth_threshold_lots"] else "ordinary"
        if window.get("condition") != expected_condition:
            raise ValueError("condition differs from registered prefix proxy")
    session_hashes = {}
    for window in windows:
        if "file" in window:
            name = window["file"]
            if Path(name).name != name or name in {"", ".", ".."}:
                raise ValueError("unsafe session path")
            if _sha(sessions / name) != window["sha256"]:
                raise ValueError("prepared session hash differs")
            session_hashes[name] = window["sha256"]
    raw = Path(raw_archive_path) if raw_archive_path is not None else sessions.parent / "raw" / plan["source"]["file"]
    raw_limit = min(MAX_FILE_BYTES, plan["source"]["maximum_bytes"])
    if not raw.is_file() or _sha(raw, raw_limit) != manifest["source_sha256"]:
        raise ValueError("missing, oversized or mismatched original raw archive")
    output.mkdir(parents=True, exist_ok=False)
    used_bytes = 0

    def write_json(name: str, value: dict, *, budgeted: bool = True) -> None:
        nonlocal used_bytes
        path = output / name
        encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        previous = path.stat().st_size if path.exists() else 0
        if budgeted and used_bytes - previous + len(encoded) > output_limit:
            raise RuntimeError("study output exceeds declared1GiB limit")
        path.write_bytes(encoded)
        used_bytes += len(encoded) - previous

    registration = {"schema_version": 2, "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "preparation_plan_sha256": manifest.get("plan_sha256"),
                    "preparation_plan_note": "preparation identity retained; later compute/benchmark amendment was frozen before any outcome evaluation",
                    "source_hashes": _source_hashes(), "session_hashes": session_hashes,
                    "native_binary_sha256": _native_hash(), "runtime_environment": {"platform": platform.platform(), "python": platform.python_version()},
                    "raw_archive_file": plan["source"]["file"], "raw_archive_sha256": _sha(raw, raw_limit), "raw_archive_max_bytes": raw_limit,
                    "plan": plan, "planning_config": asdict(config), "test_only": plan.get("test_only") is True,
                    "calibration_samples_per_policy": calibration_samples, "bootstrap_samples": bootstrap_samples,
                    "bootstrap_seed": 1234, "decision_budget_ns": DECISION_BUDGET_NS, "output_limit_bytes": output_limit}
    rows: list[dict] = []
    exclusions: list[dict] = []
    count_per_window = math.prod(len(values) for values in (plan["policies"], plan["sides"], plan["quantities_lots"], plan["deadlines_seconds"], plan["scenarios"], modes))
    attempts = len(windows) * count_per_window
    eligible_attempts = sum(window["status"] == "included" for window in windows) * count_per_window
    excluded_trials = 0
    try:
        write_json("registration.json", registration)
        write_json("status.json", {"status": "calibrating", "executed": 0, "attempts": attempts})
        identity = {name: registration[name] for name in ("plan_sha256", "manifest_sha256", "source_hashes", "raw_archive_sha256")}
        identity["planning_config"] = json.loads(json.dumps(asdict(config)))
        if calibration_path is None:
            calibration = _calibrate(windows, sessions, plan, config, calibration_samples)
            calibration["identity"] = identity
            calibration["measurement_environment"] = registration["runtime_environment"] | {"native_binary_sha256": registration["native_binary_sha256"]}
            registration["calibration_origin"] = "fresh_development_measurement"
        else:
            calibration_path = Path(calibration_path)
            calibration_bytes = _read_bytes(calibration_path, 16 * 1024**2)
            calibration = json.loads(calibration_bytes)
            registration["calibration_origin"] = "reused_frozen_model_durations"
            registration["provided_calibration_sha256"] = hashlib.sha256(calibration_bytes).hexdigest()
        _validate_calibration(calibration, identity, windows, sessions, plan, calibration_samples)
        write_json("calibration.json", calibration)
        _check_frozen(registration, sessions, plan_path, raw_archive_path=raw)
        registration["calibration_sha256"] = _sha(output / "calibration.json")
        write_json("registration.json", registration)
        with (output / "traces.jsonl").open("x") as traces:
            for window in windows:
                _check_frozen(registration, sessions, plan_path, session_name=window.get("file"), complete=False, raw_archive_path=raw)
                if _sha(output / "calibration.json") != registration["calibration_sha256"]:
                    raise ValueError("frozen calibration changed")
                base_labels = {"session": window["market_slug"], "split": window["split"], "coin": window["coin"],
                               "opening_day": window["opening_utc_day"], "condition": (window.get("condition") or "unclassified")}
                if window["status"] != "included":
                    exclusions.append({**base_labels, "policies": plan["policies"], "attempt_count": count_per_window,
                                       "reason": "prepared_window_exclusion", "details": window["reasons"]})
                    excluded_trials += count_per_window
                else:
                    events = _read_events(sessions / window["file"])
                    parent_prefix, _, _, benchmark2, depth, benchmark_capture_ns = _prefix(window, sessions)
                    window_trials = []
                    for side, size, deadline_s, specification, mode in product(
                            plan["sides"], plan["quantities_lots"], plan["deadlines_seconds"], plan["scenarios"], modes):
                        labels = {**base_labels, "side": side, "size": size, "deadline_s": deadline_s,
                                  "execution_scenario": specification["name"], "compute_mode": mode,
                                  "scenario": specification["name"] + "/" + mode}
                        if size > 10_000 or size * 100 > depth:
                            exclusions.append({**labels, "policies": plan["policies"], "attempt_count": len(plan["policies"]), "reason": "shared_initial_small_order_cap"})
                            excluded_trials += len(plan["policies"])
                            continue
                        start = window["parent_start_ns"]
                        intent = Intent(side, size, start, start + deadline_s * NS,
                                        interval_ns=plan["decision_interval_seconds"] * NS,
                                        penalty_ticks=plan["unfilled_penalty_ticks"], max_quantity=10_000)
                        completed, failures = [], []
                        for name in plan["policies"]:
                            duration = calibration["policies"][name]["declared_duration_ns"] if mode == "measured_development_compute" else 0
                            execution = {key: value for key, value in specification.items() if key != "name"}
                            execution["max_staleness_ns"] = plan["capture_watchdog_ns"]
                            scenario = Scenario(**execution, policy_duration_ns=duration, decision_budget_ns=DECISION_BUDGET_NS)
                            try:
                                simulation = run(events, intent, _policy(name, config), scenario,
                                                 recording_end_ns=window["recording_end_ns"], benchmark2=benchmark2)
                            except ValueError as error:
                                if "exceeds 1%" not in str(error):
                                    raise
                                failures.append({"policy": name, "reason": str(error)})
                                continue
                            row = {**labels, "policy": name, "benchmark2": benchmark2,
                                   "benchmark_capture_ns": benchmark_capture_ns, "benchmark_event": parent_prefix[-1].index,
                                   "filled": simulation.filled, "unfilled": simulation.unfilled,
                                   "cash": simulation.cash, "inventory": simulation.inventory, "fees": simulation.fees,
                                   "shortfall2": simulation.shortfall2, "cost_ticks_per_lot": simulation.shortfall2 / (2 * size),
                                   "completion": simulation.filled / size, "policy_duration_ns": duration,
                                   "missed_decisions": sum(item["fallback"] == "noop" for item in simulation.decisions)}
                            completed.append((simulation, row))
                        if failures:
                            if completed or len(failures) != len(plan["policies"]):
                                raise AssertionError("eligibility differs by policy inside a matched parent/scenario group")
                            exclusions.append({**labels, "policies": plan["policies"], "attempt_count": len(failures),
                                               "reason": "shared_observed_small_order_cap", "details": failures})
                            excluded_trials += len(failures)
                        else:
                            window_trials.extend(completed)
                    sql_reports = reconcile_many([simulation for simulation, _ in window_trials])
                    if len(sql_reports) != len(window_trials):
                        raise AssertionError("SQL omitted a trial")
                    _check_frozen(registration, sessions, plan_path, session_name=window.get("file"), complete=False, raw_archive_path=raw)
                    for (simulation, row), sql in zip(window_trials, sql_reports):
                        if sql["violations"]:
                            raise AssertionError(sql)
                        row.update(sql_transitions=sql["transitions"], sql_fills=sql["fills"])
                        encoded = json.dumps({"labels": row, "policy": row["policy"], "simulation": simulation.as_dict(), "sql": sql}, separators=(",", ":")) + "\n"
                        size_bytes = len(encoded.encode())
                        if used_bytes + size_bytes > output_limit:
                            raise RuntimeError("study output exceeds declared1GiB limit")
                        traces.write(encoded)
                        used_bytes += size_bytes
                        rows.append(row)
                    traces.flush()
                write_json("progress.json", {"status": "evaluating", "last_session": window["market_slug"],
                                             "executed": len(rows), "attempts": attempts,
                                             "excluded_trials": excluded_trials, "exclusion_records": len(exclusions)})
        if attempts != len(rows) + excluded_trials:
            raise AssertionError("attempt registry does not conserve configurations")
        _check_frozen(registration, sessions, plan_path, raw_archive_path=raw)
        dimensions = ("split", "policy", "scenario", "execution_scenario", "compute_mode", "side", "size", "deadline_s", "condition")
        summary = _summary(rows, dimensions)
        asset_summary = _summary(rows, dimensions + ("coin",))
        day_summary = _summary(rows, dimensions + ("opening_day",))
        stability = _stability(rows, plan, bootstrap_samples)
        _check_frozen(registration, sessions, plan_path, raw_archive_path=raw)
        coverage = []
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for window in windows:
            groups[(window["split"], window["opening_utc_day"], window["coin"], (window.get("condition") or "unclassified"), window["status"])].append(window)
        for key, values in sorted(groups.items()):
            coverage.append(dict(zip(("split", "opening_day", "coin", "condition", "status"), key)) | {"windows": len(values)})
        executed_coverage = []
        executed_groups: dict[tuple, set[str]] = defaultdict(set)
        for row in rows:
            executed_groups[(row["split"], row["opening_day"], row["coin"], row["condition"])].add(row["session"])
        for key, values in sorted(executed_groups.items()):
            executed_coverage.append(dict(zip(("split", "opening_day", "coin", "condition"), key)) | {"windows": len(values)})
        report = {"registration": registration, "attempts": attempts, "eligible_window_attempts": eligible_attempts,
                  "executed": len(rows), "excluded_trials": excluded_trials, "excluded": exclusions,
                  "summary": summary, "asset_summary": asset_summary, "day_summary": day_summary,
                  "condition_coverage": coverage, "executed_condition_coverage": executed_coverage, "stability": stability, "rows": rows,
                  "calibration": {key: value for key, value in calibration.items() if key != "policies"} | {
                      "policies": {name: {key: value for key, value in item.items() if key != "raw_ns"} for name, item in calibration["policies"].items()}},
                  "limits": manifest["limitations"] + ["one confirmation opening day; no independent-day confidence interval",
                                                         "fixed per-policy development p99 work sensitivity is not a calibrated runtime distribution"],
                  "status": "complete"}
        write_json("results.json", report)
        write_json("status.json", {"status": "complete", "attempts": attempts, "executed": len(rows), "excluded_trials": excluded_trials})
        return report
    except BaseException as error:
        write_json("status.json", {"status": "failed", "error_type": type(error).__name__, "error": str(error),
                                   "executed": len(rows), "attempts": attempts, "excluded_trials": excluded_trials}, budgeted=False)
        raise
