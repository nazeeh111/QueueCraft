"""Prospective source normalization invariants, without policy evaluations."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

module_path = Path(__file__).resolve().parents[1] / "tools/prepare_prospective.py"
spec = importlib.util.spec_from_file_location("prepare_prospective", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

NS = 1_000_000_000
OPENING = 1787271300 * NS


class ProspectiveTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((Path(__file__).resolve().parents[1] / "docs/PROSPECTIVE_PLAN.json").read_text())

    def row(self, seconds, **changes):
        row = {"market_slug": "btc-updown-15m-1787271300", "coin": "btc", "contract_length": "15m", "token_id": "token", "market_end_at": OPENING + 900 * NS, "captured_at": OPENING + seconds * NS, "bid_prices": [.49], "bid_sizes": [100], "ask_prices": [.50], "ask_sizes": [100]}
        row.update(changes)
        return row

    def test_true15m_opening_and_terminal_watchdog(self):
        info, events = module.build_window([self.row(60)], self.plan)
        self.assertEqual(info["opening_ns"], OPENING)
        self.assertEqual(info["parent_start_ns"], OPENING + 60 * NS)
        self.assertEqual(info["recording_end_ns"], OPENING + 90 * NS)
        self.assertEqual(info["status"], "included")
        self.assertEqual(events[-1], (OPENING + 65 * NS + 1, "G", [("B", 1, 0)]))
        self.assertLess(events[-1][0], info["recording_end_ns"])

    def test_future_payload_cannot_change_parent_prefix(self):
        prefix = [self.row(59)]
        a, ea = module.build_window(prefix + [self.row(70)], self.plan)
        b, eb = module.build_window(prefix + [self.row(70, bid_prices=[.99], ask_prices=[.01])], self.plan)
        for field in ("prefix_spread_ticks", "prefix_min_top10_lots", "prefix_source_capture_ns", "parent_start_ns", "recording_end_ns", "status"):
            self.assertEqual(a[field], b[field])
        self.assertEqual([e for e in ea if e[0] <= a["parent_start_ns"]], [e for e in eb if e[0] <= b["parent_start_ns"]])

    def test_watchdog_and_resync_at_exact_boundary(self):
        info, events = module.build_window([self.row(54), self.row(59)], self.plan)
        self.assertEqual(info["status"], "included")
        self.assertFalse(any(k == "G" and t < OPENING + 59 * NS for t, k, _ in events))
        invalid, ev = module.build_window([self.row(54)], self.plan)
        self.assertEqual(invalid["status"], "excluded")
        self.assertIn("no valid complete observation at parent start", invalid["reasons"])

    def test_confirmation_does_not_choose_depth_threshold(self):
        windows = [{"status": "included", "split": "development", "prefix_min_top10_lots": v} for v in [100, 200, 300, 400, 500]]
        windows += [{"status": "included", "split": "confirmation", "prefix_min_top10_lots": 0}]
        self.assertEqual(module.development_depth_threshold(windows), 200)
        windows[-1]["prefix_min_top10_lots"] = 10**12
        self.assertEqual(module.development_depth_threshold(windows), 200)
        windows[0]["status"] = "excluded"
        self.assertEqual(module.development_depth_threshold(windows), 200)

    def test_safe_metadata_and_no_future_label_dependency(self):
        bad, _ = module.build_window([self.row(60, market_slug="../escape")], self.plan)
        self.assertIn("15m identifier/opening metadata mismatch", bad["reasons"])
        a, ea = module.build_window([self.row(60, winner="yes", is_winning_outcome=True)], self.plan)
        b, eb = module.build_window([self.row(60, winner="no", is_winning_outcome=False)], self.plan)
        self.assertEqual(a, b)
        self.assertEqual(ea, eb)

    def test_day_split_is_chronological_and_fixed(self):
        development = self.plan["development_opening_utc_days"]
        confirmation = self.plan["confirmation_opening_utc_days"]
        self.assertLess(max(development), min(confirmation))
        self.assertEqual(module.split_for("2026-08-23", self.plan), "development")
        self.assertEqual(module.split_for("2026-08-24", self.plan), "confirmation")
        self.assertEqual(module.split_for("2026-08-25", self.plan), "excluded_day")


if __name__ == "__main__":
    unittest.main()
