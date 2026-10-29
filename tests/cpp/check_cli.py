"""Check standalone CLI books/accounting against the independent Python model."""

import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from queuecraft.reference import Reference, parse_events, replay


def main():
    source = Path(sys.argv[1]).resolve()
    report = Path(sys.argv[2]).resolve()
    if report.exists():
        raise SystemExit("report exists; choose a fresh result")
    text = source.read_text()
    expected_books = replay(text)
    events = parse_events(text)
    reference = Reference()
    for event in events:
        if event.receive_ns != events[0].receive_ns:
            break
        reference.apply(event.csv())
    expected_order = reference.take("buy", 3, 1_000, 1_000_000)
    executable = ROOT / "build/queuecraft-core"
    with tempfile.TemporaryDirectory(prefix="queuecraft-cli-check-") as temporary:
        root = Path(temporary)
        output = root / "result"
        command = [str(executable), str(source), str(output), "buy", "3", "0", "1000", "1000000"]
        first = subprocess.run(command, capture_output=True, text=True, check=True)
        actual_books = (output / "books.csv").read_text()
        assert actual_books == expected_books, "complete CLI book trace differs from independent reference"
        fills = [{k: int(v) for k, v in row.items() if k != "event"} for row in csv.DictReader(io.StringIO((output / "fills.csv").read_text()))]
        assert fills == expected_order["fills"], "CLI fill trace differs from independent accounting"
        ledger = next(csv.DictReader(io.StringIO((output / "ledger.csv").read_text())))
        for key in ("event", "exchange_ns", "receive_ns", "filled", "remaining", "cash", "inventory", "fees"):
            assert int(ledger[key]) == expected_order[key], f"CLI ledger mismatch at {key}"
        saved = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
        again = subprocess.run(command, capture_output=True, text=True)
        assert again.returncode == 2 and "output exists" in again.stderr
        assert saved == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}, "failed overwrite changed output"
        truncated = root / "truncated.csv"
        truncated.write_text(text[:-1])
        bad = subprocess.run([str(executable), str(truncated), str(root / "invalid")], capture_output=True, text=True)
        assert bad.returncode == 2 and not (root / "invalid").exists()
        oversized = root / "oversized.csv"
        with oversized.open("wb") as file:
            file.truncate(64 * 1024 * 1024 + 1)
        bound = subprocess.run([str(executable), str(oversized), str(root / "oversized-result")], capture_output=True, text=True)
        assert bound.returncode == 2 and "exceeds 64 MiB" in bound.stderr and not (root / "oversized-result").exists()
    result = {
        "status": "pass", "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "cli_source_sha256": hashlib.sha256((ROOT / "src/main.cpp").read_bytes()).hexdigest(),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "book_trace_sha256": hashlib.sha256(actual_books.encode()).hexdigest(),
        "all_book_levels_equal_independent_python": True, "fills_and_all_ledger_fields_equal": True,
        "existing_output_preserved": True, "truncation_rejected_before_output": True,
        "oversized_file_rejected_before_output": True, "order": expected_order,
        "stdout": first.stdout.split("/result", 1)[-1].strip(),
    }
    with report.open("x") as file:
        file.write(json.dumps(result, indent=2) + "\n")
    print(report)


if __name__ == "__main__":
    main()
