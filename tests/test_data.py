import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from queuecraft.data import fixed, levels, normalize, validate_snapshot


class DataTests(unittest.TestCase):
    def test_exact_units_and_rejection(self):
        self.assertEqual(fixed("0.47", 100), 47)
        self.assertEqual(fixed("67.30", 100), 6730)
        for value in ("0.001", "NaN", "Infinity", "-1", str(2**63)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fixed(value, 100)

    def test_ladders(self):
        self.assertEqual(levels([.46, .47], [2, 1], "B"), [("B", 470, 100), ("B", 460, 200)])
        self.assertEqual(levels([.999], [1], "A"), [("A", 999, 100)])
        with self.assertRaises(ValueError):
            levels([.9999], [1], "A")
        for prices, sizes in (([], []), ([.4], []), ([.4, .4], [1, 1]), ([.4], [0])):
            with self.assertRaises(ValueError):
                levels(prices, sizes, "B")
        with self.assertRaises(ValueError):
            validate_snapshot(dict(bid_prices=[.5], bid_sizes=[1], ask_prices=[.5], ask_sizes=[1]))

    @unittest.skipUnless(importlib.util.find_spec("duckdb"), "DuckDB required for archive fixtures")
    def test_split_labels_gap_and_resynchronization(self):
        import duckdb
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "fixture.parquet"
            con = duckdb.connect()
            con.execute("CREATE TABLE source AS SELECT 'market-' || cast(i//3 AS varchar) market_slug, 'token' token_id, 'Up' outcome, epoch_ms(1000000 + (i//3)*300000) market_end_at, epoch_ms(700000 + (i//3)*300000 + (i%3)*10000) captured_at, [.40]::DOUBLE[] bid_prices, [1.0]::DOUBLE[] bid_sizes, (CASE WHEN i%3=1 THEN [.39] ELSE [.41] END)::DOUBLE[] ask_prices, [1.0]::DOUBLE[] ask_sizes, 'future-label' winner FROM range(6) t(i)")
            con.execute("COPY source TO ? (FORMAT PARQUET)", [str(source)])
            first = normalize(source, root / "first")
            self.assertEqual(first["counts"], {"development": 1, "confirmation": 1})
            self.assertTrue(all(w["invalidations"] >= 1 for w in first["windows"]))
            for window in first["windows"]:
                content = (root / "first" / window["file"]).read_text()
                self.assertNotIn("future-label", content)
                self.assertIn(",-1,", content)
                self.assertIn(",G,B,1,0", content)
                self.assertGreater(content.rfind(",S,"), content.find(",G,"))
                self.assertEqual(window["sha256"], hashlib.sha256(content.encode()).hexdigest())
            # Changing every future label has no effect on replay bytes.
            con.execute("UPDATE source SET winner='opposite-label'")
            second_source = root / "other.parquet"
            con.execute("COPY source TO ? (FORMAT PARQUET)", [str(second_source)])
            second = normalize(second_source, root / "second")
            self.assertEqual([w["sha256"] for w in first["windows"]], [w["sha256"] for w in second["windows"]])
            with self.assertRaises(FileExistsError):
                normalize(source, root / "first")
            con.close()


if __name__ == "__main__":
    unittest.main()
