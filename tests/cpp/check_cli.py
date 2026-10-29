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
    if len(sys.argv) != 4:
        raise SystemExit("usage: check_cli.py INPUT.csv RECORDING_METADATA.json FRESH_REPORT.json")
    source = Path(sys.argv[1]).resolve()
    metadata = Path(sys.argv[2]).resolve()
    report = Path(sys.argv[3]).resolve()
    if report.exists():
        raise SystemExit("report exists; choose a fresh result")
    text = source.read_text()
    expected_books = replay(text)
    events = parse_events(text)
    # Recorder metadata is authoritative for coverage; the last payload is not.
    recording_end = json.loads(metadata.read_text())["recording_end_ns"]
    if type(recording_end) is not int or not 0 <= recording_end <= 2**63 - 1:
        raise ValueError("recording metadata requires nonnegative exact int recording_end_ns")
    if any(event.receive_ns > recording_end for event in events):
        raise ValueError("input payload exceeds declared metadata coverage")
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
        command = [str(executable), str(source), str(output), "buy", "3", "0", "1000", "1000000", "--recording-end-ns", str(recording_end)]
        first = subprocess.run(command, capture_output=True, text=True, check=True)
        actual_books = (output / "books.csv").read_text()
        assert actual_books == expected_books, "complete CLI book trace differs from independent reference"
        fills = [{k: int(v) for k, v in row.items() if k != "event"} for row in csv.DictReader(io.StringIO((output / "fills.csv").read_text()))]
        assert fills == expected_order["fills"], "CLI fill trace differs from independent accounting"
        ledger = next(csv.DictReader(io.StringIO((output / "ledger.csv").read_text())))
        assert int(ledger["recording_end_ns"]) == recording_end
        for key in ("event", "exchange_ns", "receive_ns", "filled", "remaining", "cash", "inventory", "fees"):
            assert int(ledger[key]) == expected_order[key], f"CLI ledger mismatch at {key}"
        saved = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
        again = subprocess.run(command, capture_output=True, text=True)
        assert again.returncode == 2 and "output exists" in again.stderr
        assert saved == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}, "failed overwrite changed output"
        missing = subprocess.run([str(executable), str(source), str(root / "missing-bound"), "buy"], capture_output=True, text=True)
        assert missing.returncode == 2 and "--recording-end-ns" in missing.stderr and not (root / "missing-bound").exists()
        replay_only = root / "replay-only"
        subprocess.run([str(executable), str(source), str(replay_only)], capture_output=True, text=True, check=True)
        assert (replay_only / "books.csv").read_text() == expected_books
        assert not (replay_only / "ledger.csv").exists()
        # The end is fixed recorder metadata, not inferred from either payload.
        quiet = "event,exchange_ns,receive_ns,kind,side,price,quantity\n0,-1,0,S,B,99,5\n0,-1,0,S,A,101,5\n"
        appended = quiet + "1,-1,2,S,B,299,1\n1,-1,2,S,A,301,1\n"
        snapshots = []
        for name, content in (("quiet", quiet), ("appended", appended)):
            fixture = root / f"{name}.csv"
            fixture.write_text(content)
            destination = root / name
            subprocess.run([str(executable), str(fixture), str(destination), "buy", "5", "1", "0", "1000000", "--recording-end-ns", "2"], capture_output=True, text=True, check=True)
            snapshots.append(((destination / "fills.csv").read_text(), (destination / "ledger.csv").read_text()))
        assert snapshots[0] == snapshots[1], "future append changed an earlier covered CLI order"
        assert "101,5,505,0" in snapshots[0][0], "quiet covered order did not fill"
        late = root / "late"
        subprocess.run([str(executable), str(root / "quiet.csv"), str(late), "buy", "5", "3", "0", "1000000", "--recording-end-ns", "2"], capture_output=True, text=True, check=True)
        assert int(next(csv.DictReader(io.StringIO((late / "ledger.csv").read_text())))["filled"]) == 0
        outside = subprocess.run([str(executable), str(root / "appended.csv"), str(root / "outside"), "buy", "--recording-end-ns", "1"], capture_output=True, text=True)
        assert outside.returncode == 2 and "exceeds declared recording" in outside.stderr and not (root / "outside").exists()
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
        "recording_end_ns": recording_end, "recording_metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
        "mandatory_order_boundary": True, "replay_without_boundary": True,
        "fixed_boundary_future_append_equal": True, "late_arrival_unfilled": True, "out_of_bounds_rejected": True,
        "existing_output_preserved": True, "truncation_rejected_before_output": True,
        "oversized_file_rejected_before_output": True, "order": expected_order,
        "stdout": first.stdout.split("/result", 1)[-1].strip(),
    }
    with report.open("x") as file:
        file.write(json.dumps(result, indent=2) + "\n")
    print(report)


if __name__ == "__main__":
    main()
