"""Registered multi-window study and paired scenario stability analysis."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from itertools import combinations, product
import json
from pathlib import Path
import random
import statistics

from .policies import POLICIES
from .reconcile import reconcile_many
from .sdk import Intent, Scenario, events_from_csv, run


def bootstrap(values: list[float], seed: int = 1234) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(1000))
    return [means[24], means[974]]


def study(sessions: Path, plan_path: Path, output: Path) -> dict:
    manifest_bytes = (sessions / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    output.mkdir(parents=True, exist_ok=False)
    sources = {str(p.relative_to(Path(__file__).parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*")) if p.suffix in {".py", ".sql", ".so"}}
    (output / "registration.json").write_text(json.dumps({"plan_sha256": hashlib.sha256(plan_bytes).hexdigest(), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "source_hashes": sources, "plan": plan}, indent=2) + "\n")
    loaded = {}
    spreads = []
    for window in manifest["windows"]:
        if window["status"] != "included":
            continue
        source = sessions / window["file"]
        text = source.read_text()
        if hashlib.sha256(source.read_bytes()).hexdigest() != window["sha256"]:
            raise ValueError("frozen session hash changed")
        events = events_from_csv(text)
        first = next((event for event in events if event.kind == "S"), None)
        loaded[window["market_slug"]] = (events, first)
        if first and window["split"] == "development":
            bids = [p for side, p, _ in first.levels if side == "B"]
            asks = [p for side, p, _ in first.levels if side == "A"]
            spreads.append(min(asks) - max(bids))
    if not spreads:
        raise ValueError("no development benchmark observations")
    threshold = sorted(spreads)[int(0.75 * (len(spreads) - 1))]
    rows, failures, attempts = [], [], 0
    trace_path = output / "traces.jsonl"
    with trace_path.open("x") as traces:
        for window in manifest["windows"]:
            window_trials = []
            if window["market_slug"] not in loaded:
                failures.append({"session": window["market_slug"], "reason": window["reasons"]})
                continue
            events, first = loaded[window["market_slug"]]
            for side, size, deadline_s, specification in product(plan["sides"], plan["quantities_lots"], plan["deadlines_seconds"], plan["scenarios"]):
                attempts += len(plan["policies"])
                labels = {"session": window["market_slug"], "split": window["split"], "side": side, "size": size, "deadline_s": deadline_s, "scenario": specification["name"]}
                if first is None:
                    failures.append({**labels, "policies": plan["policies"], "reason": "no valid initial snapshot"})
                    continue
                start = first.receive_ns
                deadline = start + deadline_s * 1_000_000_000
                if events[-1].receive_ns < deadline + 1_000_000_000:
                    failures.append({**labels, "policies": plan["policies"], "reason": "insufficient recorded horizon"})
                    continue
                # Preserve contiguous indices and all events leading to start.
                prefix = tuple(event for event in events if event.receive_ns <= deadline + 1_000_000_000)
                scenario = Scenario(**{k: v for k, v in specification.items() if k != "name"})
                intent = Intent(side, size, start, deadline, penalty_ticks=plan["unfilled_penalty_ticks"], max_quantity=10_000)
                bids = [p for s, p, _ in first.levels if s == "B"]
                asks = [p for s, p, _ in first.levels if s == "A"]
                condition = "wide_spread" if min(asks) - max(bids) >= threshold else "ordinary"
                # Eligibility checked with the same initial information before
                # all policies; if unsupported, retain the whole matched group.
                opposite_depth = min(sum(q for _, _, q in sorted((v for v in first.levels if v[0] == "B"), key=lambda x: x[1], reverse=True)[:10]), sum(q for _, _, q in sorted((v for v in first.levels if v[0] == "A"), key=lambda x: x[1])[:10]))
                if size * 100 > opposite_depth:
                    failures.append({**labels, "policies": plan["policies"], "reason": "initial small-order cap"})
                    continue
                for policy in plan["policies"]:
                    try:
                        result = run(prefix, intent, POLICIES[policy](), scenario)
                    except ValueError as error:
                        if "exceeds 1%" not in str(error) and "benchmark" not in str(error):
                            raise
                        failures.append({**labels, "policy": policy, "reason": str(error)})
                        continue
                    row = {**labels, "policy": policy, "condition": condition, "benchmark2": result.benchmark2, "filled": result.filled, "unfilled": result.unfilled, "fees": result.fees, "cash": result.cash, "inventory": result.inventory, "shortfall2": result.shortfall2, "cost_ticks_per_lot": result.shortfall2 / (2 * size), "completion": result.filled / size}
                    window_trials.append((result, row))
            sql_reports = reconcile_many([r for r, _ in window_trials])
            for (result, row), sql in zip(window_trials, sql_reports):
                if sql["violations"]:
                    raise AssertionError(sql)
                row.update(sql_transitions=sql["transitions"], sql_fills=sql["fills"])
                rows.append(row)
                labels = {k: row[k] for k in ("session", "split", "side", "size", "deadline_s", "scenario")}
                traces.write(json.dumps({"labels": labels, "policy": row["policy"], "simulation": result.as_dict(), "sql": sql}, separators=(",", ":")) + "\n")
            # Durable progress checkpoint, not a success claim.
            (output / "progress.json").write_text(json.dumps({"last_session": window["market_slug"], "executed": len(rows), "exclusions": len(failures)}) + "\n")
    groups = {}
    for row in rows:
        key = (row["split"], row["policy"], row["scenario"], row["side"], row["size"], row["deadline_s"], row["condition"])
        groups.setdefault(key, []).append(row)
    summary = []
    for key, group in sorted(groups.items()):
        costs = sorted(r["cost_ticks_per_lot"] for r in group)
        summary.append(dict(zip(("split", "policy", "scenario", "side", "size", "deadline_s", "condition"), key)) | {"windows": len(group), "mean_cost": statistics.mean(costs), "p95_cost": costs[min(len(costs)-1, int(0.95*len(costs)))], "mean_completion": statistics.mean(r["completion"] for r in group), "fees": sum(r["fees"] for r in group), "unfilled": sum(r["unfilled"] for r in group)})
    indexed = {(r["session"], r["split"], r["policy"], r["scenario"], r["side"], r["size"], r["deadline_s"]): r for r in rows}
    stability = []
    for split, a_b, side, size, deadline in product(("development", "confirmation"), combinations(plan["policies"], 2), plan["sides"], plan["quantities_lots"], plan["deadlines_seconds"]):
        a, b = a_b
        scenarios = []
        for specification in plan["scenarios"]:
            scenario = specification["name"]
            diffs = []
            for window in manifest["windows"]:
                x = indexed.get((window["market_slug"], split, a, scenario, side, size, deadline))
                y = indexed.get((window["market_slug"], split, b, scenario, side, size, deadline))
                if x and y:
                    diffs.append(x["cost_ticks_per_lot"] - y["cost_ticks_per_lot"])
            interval = bootstrap(diffs)
            scenarios.append({"scenario": scenario, "windows": len(diffs), "difference_a_minus_b": statistics.mean(diffs) if diffs else None, "window_bootstrap95": interval if diffs else None})
        values = [s["difference_a_minus_b"] for s in scenarios if s["difference_a_minus_b"] is not None]
        reversal = bool(values) and min(values) < 0 < max(values)
        unresolved = any(s["window_bootstrap95"] is None or s["window_bootstrap95"][0] <= 0 <= s["window_bootstrap95"][1] for s in scenarios)
        stability.append({"split": split, "a": a, "b": b, "side": side, "size": size, "deadline_s": deadline, "status": "unresolved" if unresolved else "reversal" if reversal else "stable", "mean_sign_reversal": reversal, "scenarios": scenarios})
    for name, digest in sources.items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != digest:
            raise ValueError("source changed during study; retain partial output and rerun")
    report = {"registration": json.loads((output / "registration.json").read_text()), "attempts": attempts, "executed": len(rows), "excluded": failures, "stress_threshold_initial_spread_ticks": threshold, "summary": summary, "stability": stability, "rows": rows, "limits": manifest["limitations"]}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
