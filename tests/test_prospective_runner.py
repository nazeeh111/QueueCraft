"""Tiny synthetic-only runner tests; never evaluates the real15m corpus."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from queuecraft import Event
from queuecraft import prospective

NS = 1_000_000_000
ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ProspectiveRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="queuecraft-runner-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / "data" / "sessions"
        self.sessions.mkdir(parents=True)
        raw = self.sessions.parent / "raw"
        raw.mkdir()
        (raw / "fixture.parquet").write_bytes(b"synthetic raw fixture, not market evidence")
        plan = json.loads((ROOT / "docs/PROSPECTIVE_PLAN.json").read_text())
        plan.update(test_only=True, policies=["immediate", "twap"], sides=["buy", "sell"],
                    quantities_lots=[1], deadlines_seconds=[1])
        plan["source"]["file"] = "fixture.parquet"
        plan["source"]["sha256"] = sha(raw / "fixture.parquet")
        plan["scenarios"] = [plan["scenarios"][0], {**plan["scenarios"][0], "name": "delayed", "latency_ns": NS//4}]
        self.plan = plan
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(plan))
        windows = []
        for day, split in (("2026-08-21", "development"), ("2026-08-24", "confirmation")):
            midnight = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()) * NS
            for index, condition in enumerate(("ordinary", "stress")):
                opening = midnight + index * 900 * NS
                start = opening + 60 * NS
                name = f"{'btc' if index == 0 else 'eth'}-updown-15m-{opening//NS}"
                ask = 102 if condition == "ordinary" else 120
                events = tuple(Event(i, -1, opening + second*NS, "S", (("B", 100, 100_000), ("A", ask, 100_000)))
                               for i, second in enumerate((59, 60, 61, 90)))
                text = events[0].csv() + "".join(event.csv().split("\n", 1)[1] for event in events[1:])
                file = self.sessions / (name + ".csv")
                file.write_text(text)
                windows.append({"market_slug": name, "coin": "btc" if index == 0 else "eth", "condition": condition,
                                "file": file.name, "sha256": sha(file), "opening_ns": opening,
                                "parent_start_ns": start, "recording_end_ns": opening + 90*NS,
                                "settlement_ns": opening + 900*NS, "opening_utc_day": day,
                                "split": split, "status": "included", "reasons": [],
                                "prefix_min_top10_lots": 100_000, "prefix_spread_ticks": ask-100})
        windows.append({"market_slug": "excluded-synthetic-window", "coin": "zec", "opening_utc_day": "2026-08-24",
                        "split": "confirmation", "status": "excluded", "reasons": ["synthetic incomplete prefix"]})
        self.manifest = {"source_sha256": plan["source"]["sha256"], "plan_sha256": sha(self.plan_path),
                         "depth_threshold_lots": 100_000, "windows": windows,
                         "limitations": ["synthetic-only runner fixture"]}
        self.write_manifest()
        self.settings = {"calibration_samples": 4, "bootstrap_samples": 20}

    def write_manifest(self):
        (self.sessions / "manifest.json").write_text(json.dumps(self.manifest))

    def execute(self, name="first", **kwargs):
        clock = itertools.count(step=111)
        with patch.object(prospective.time, "perf_counter_ns", side_effect=lambda: next(clock)):
            return prospective.study(self.sessions, self.plan_path, self.root / name,
                                     _test_settings=self.settings, **kwargs)

    def test_complete_tiny_matrix_accounts_for_all_trials_and_strata(self):
        report = self.execute()
        self.assertEqual((report["attempts"], report["eligible_window_attempts"], report["executed"], report["excluded_trials"]), (80, 64, 64, 16))
        self.assertEqual(report["attempts"], report["executed"] + sum(item["attempt_count"] for item in report["excluded"]))
        self.assertEqual({row["condition"] for row in report["rows"]}, {"ordinary", "stress"})
        self.assertEqual({cell["condition"] for cell in report["stability"]}, {"all", "ordinary", "stress"})
        self.assertEqual({item["coin"] for item in report["asset_summary"]}, {"btc", "eth"})
        self.assertEqual({item["opening_day"] for item in report["day_summary"]}, {"2026-08-21", "2026-08-24"})
        self.assertTrue(all(item["days"] == 1 for cell in report["stability"] for item in cell["scenarios"]))
        self.assertTrue(all(item["day_interval"] is None for cell in report["stability"] for item in cell["scenarios"]))
        traces = [json.loads(line) for line in (self.root / "first" / "traces.jsonl").read_text().splitlines()]
        self.assertEqual(len(traces), 64)
        self.assertTrue(all(not item["sql"]["violations"] for item in traces))
        for trial in traces:
            self.assertEqual(trial["simulation"]["recording_end_ns"], next(window["recording_end_ns"] for window in self.manifest["windows"] if window["market_slug"] == trial["labels"]["session"]))
        for cell in report["stability"]:
            self.assertEqual(len({item["windows"] for item in cell["scenarios"]}), 1)
        self.assertEqual(json.loads((self.root / "first" / "status.json").read_text())["status"], "complete")

    def test_reuse_frozen_calibration_never_measures_clock_and_replays_same_trace(self):
        first = self.execute()
        calibration = self.root / "first" / "calibration.json"
        with patch.object(prospective.time, "perf_counter_ns", side_effect=AssertionError("wall clock must not be remeasured")):
            second = prospective.study(self.sessions, self.plan_path, self.root / "second",
                                       calibration_path=calibration, _test_settings=self.settings)
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual(first["stability"], second["stability"])
        self.assertEqual((self.root / "first" / "traces.jsonl").read_bytes(), (self.root / "second" / "traces.jsonl").read_bytes())
        self.assertEqual(second["registration"]["calibration_origin"], "reused_frozen_model_durations")

    def test_calibration_uses_only_development_parent_prefix(self):
        config = prospective._planning_config(self.plan)
        clock = itertools.count(step=17)
        with patch.object(prospective.time, "perf_counter_ns", side_effect=lambda: next(clock)):
            a = prospective._calibrate(self.manifest["windows"], self.sessions, self.plan, config, 4)
        # Future development prices and all confirmation payloads are irrelevant
        # to measured decision work; full-source hashes are verified separately.
        for window in self.manifest["windows"]:
            if "file" not in window:
                continue
            path = self.sessions / window["file"]
            if window["split"] == "confirmation":
                path.write_text("deliberately unreadable confirmation data")
            else:
                lines = path.read_text().splitlines(keepends=True)
                lines[-1] = lines[-1].replace(",102,", ",999,").replace(",120,", ",999,")
                path.write_text("".join(lines))
        clock = itertools.count(step=17)
        with patch.object(prospective.time, "perf_counter_ns", side_effect=lambda: next(clock)):
            b = prospective._calibrate(self.manifest["windows"], self.sessions, self.plan, config, 4)
        self.assertEqual(a, b)
        self.assertTrue(all(prefix["day"] == "2026-08-21" for prefix in a["prefixes"]))

    def test_corrupt_calibration_duration_budget_and_source_are_rejected(self):
        self.execute()
        clean = json.loads((self.root / "first" / "calibration.json").read_text())
        changes = [lambda data: data["policies"]["immediate"].update(declared_duration_ns=0),
                   lambda data: data.update(shared_decision_budget_ns=2*NS),
                   lambda data: data["identity"]["source_hashes"].update({"sdk.py": "bad"}),
                   lambda data: data["prefixes"][0].update(day="2026-08-24"),
                   lambda data: data.pop("measurement_environment")]
        for index, change in enumerate(changes):
            bad = deepcopy(clean)
            change(bad)
            path = self.root / f"bad-{index}.json"
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                self.execute(f"bad-output-{index}", calibration_path=path)
            self.assertEqual(json.loads((self.root / f"bad-output-{index}" / "status.json").read_text())["status"], "failed")
            self.assertFalse((self.root / f"bad-output-{index}" / "traces.jsonl").exists())

    def test_frozen_plan_change_aborts_before_any_outcome(self):
        actual = prospective._calibrate
        def changed(*args):
            result = actual(*args)
            self.plan_path.write_text(self.plan_path.read_text() + " ")
            return result
        with patch.object(prospective, "_calibrate", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "plan or manifest changed"):
                self.execute()
        self.assertFalse((self.root / "first" / "traces.jsonl").exists())

    def test_cap_exclusions_are_shared_and_not_silently_dropped(self):
        self.plan["quantities_lots"] = [1001]
        self.plan_path.write_text(json.dumps(self.plan))
        report = self.execute()
        self.assertEqual(report["executed"], 0)
        self.assertEqual(report["excluded_trials"], report["attempts"])
        self.assertTrue(any(item["reason"] == "shared_initial_small_order_cap" for item in report["excluded"]))
        self.assertEqual(report["executed_condition_coverage"], [])

    def test_source_hash_or_sql_failure_cannot_finish_a_study(self):
        with patch.object(prospective, "reconcile_many", return_value=[{"violations": [["injected", 0]], "transitions": 0, "fills": 0}]):
            with self.assertRaisesRegex(AssertionError, "SQL omitted"):
                self.execute()
        self.assertEqual(json.loads((self.root / "first" / "status.json").read_text())["status"], "failed")
        self.assertFalse((self.root / "first" / "results.json").exists())

    def test_output_is_exclusive_and_test_overrides_cannot_touch_production(self):
        self.execute()
        saved = (self.root / "first" / "status.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual((self.root / "first" / "status.json").read_bytes(), saved)
        self.plan.pop("test_only")
        self.plan_path.write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError, "test_only"):
            self.execute("not-production")
        self.assertFalse((self.root / "not-production").exists())

    def test_stability_uses_common_windows_across_every_world(self):
        rows = []
        worlds = [scenario["name"] + "/" + mode for scenario in self.plan["scenarios"] for mode in self.plan["policy_compute_sensitivity"]["modes"]]
        for window in ("one", "two"):
            for policy in self.plan["policies"]:
                for world in worlds:
                    if window == "two" and policy == "twap" and world == worlds[-1]:
                        continue
                    rows.append({"session": window, "policy": policy, "scenario": world, "side": "buy", "size": 1,
                                 "deadline_s": 1, "split": "confirmation", "condition": "ordinary",
                                 "opening_day": "2026-08-24", "cost_ticks_per_lot": 1 if policy == "immediate" else 0})
        cells = prospective._stability(rows, self.plan, 20)
        selected = next(cell for cell in cells if cell["split"] == "confirmation" and cell["condition"] == "all" and cell["side"] == "buy")
        self.assertEqual(selected["common_windows"], 1)
        self.assertEqual(selected["unmatched_windows"], ["two"])
        self.assertEqual({item["windows"] for item in selected["scenarios"]}, {1})

    def test_separate_raw_archive_location_replays_without_private_layout(self):
        first = self.execute()
        external = self.root / "public-source" / "different-name.parquet"
        external.parent.mkdir()
        (self.sessions.parent / "raw" / "fixture.parquet").rename(external)
        with patch.object(prospective.time, "perf_counter_ns", side_effect=AssertionError("frozen calibration must replay")):
            second = prospective.study(self.sessions, self.plan_path, self.root / "relocated",
                                       raw_archive_path=external,
                                       calibration_path=self.root / "first" / "calibration.json",
                                       _test_settings=self.settings)
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual((self.root / "first" / "traces.jsonl").read_bytes(), (self.root / "relocated" / "traces.jsonl").read_bytes())
        self.assertNotIn("raw_archive_path", second["registration"])
        external.write_bytes(external.read_bytes() + b"changed after registration")
        with self.assertRaisesRegex(ValueError, "raw archive changed"):
            prospective._check_frozen(second["registration"], self.sessions, self.plan_path, raw_archive_path=external)

    def test_three_second_old_quote_uses_registered_five_second_watchdog(self):
        for window in self.manifest["windows"]:
            if window["status"] != "included":
                continue
            opening = window["opening_ns"]
            ask = 100 + window["prefix_spread_ticks"]
            events = tuple(Event(i, -1, opening + second*NS, "S", (("B", 100, 100_000), ("A", ask, 100_000)))
                           for i, second in enumerate((57, 61, 90)))
            path = self.sessions / window["file"]
            path.write_text(events[0].csv() + "".join(event.csv().split("\n", 1)[1] for event in events[1:]))
            window["sha256"] = sha(path)
        self.write_manifest()
        observations, _ = prospective._calibration_inputs(self.manifest["windows"], self.sessions, self.plan)
        self.assertTrue(all(observation.now_ns - observation.observed_receive_ns == 3*NS for observation in observations))
        self.assertTrue(all(observation.scenario.max_staleness_ns == 5*NS for observation in observations))
        self.execute()
        traces = [json.loads(line) for line in (self.root / "first" / "traces.jsonl").read_text().splitlines()]
        for trial in traces:
            simulation = trial["simulation"]
            self.assertEqual(simulation["scenario"]["max_staleness_ns"], 5*NS)
            self.assertTrue(simulation["decisions"][0]["valid"])
            if trial["policy"] == "immediate" and trial["labels"]["scenario"] == "base/zero_compute_baseline":
                self.assertEqual(simulation["fills"][0]["arrival_ns"], simulation["intent"]["start_ns"])

    def test_actual_reads_remain_bounded_when_file_grows_after_stat(self):
        class Tracking(io.BytesIO):
            def __init__(self, content):
                super().__init__(content)
                self.requests = []
                self.consumed = None
            def read(self, size=-1):
                self.requests.append(("read", size))
                return super().read(size)
            def readline(self, size=-1):
                self.requests.append(("readline", size))
                return super().readline(size)
            def close(self):
                if not self.closed:
                    self.consumed = self.tell()
                super().close()
        path = self.root / "growing.csv"
        content = prospective.HEADER.encode() + b"x" * 200
        limit = len(prospective.HEADER) + 8
        # A stale small stat cannot authorize reading the subsequently grown
        # payload. Hash, full event read and unterminated prefix row each stop
        # after at most the declared bound plus one sentinel byte.
        operations = [lambda: prospective._sha(path, max_bytes=limit),
                      lambda: prospective._read_events(path),
                      lambda: prospective._read_events(path, before_ns=NS)]
        for operation in operations:
            stream = Tracking(content)
            with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1)), \
                 patch.object(Path, "open", return_value=stream), \
                 patch.object(prospective, "MAX_FILE_BYTES", limit):
                with self.assertRaisesRegex(ValueError, "exceeds.*bound"):
                    operation()
            self.assertLessEqual(stream.consumed, limit + 1)
            self.assertTrue(all(0 < size <= limit + 1 for _, size in stream.requests))


if __name__ == "__main__":
    unittest.main()
