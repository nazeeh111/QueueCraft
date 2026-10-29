"""Run the instrumented native systems benchmark against a genuine session.

Each stage retains at least10,000 individual timing samples. The raw samples
are reduced to explicitly sampled quantiles; this is a desktop systems test,
not a measurement of exchange or network execution latency.
"""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    failure_output = output.with_suffix(".failed.json")
    if output.exists() or failure_output.exists():
        raise SystemExit("output exists; choose a fresh benchmark result")
    source_names = ["include/queuecraft/engine.hpp", "src/engine.cpp", "tools/benchmark.cpp"]
    source_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source_names}
    source_manifest = "".join(f"{name}\0{digest}\n" for name, digest in sorted(source_hashes.items())).encode()
    source_tree = hashlib.sha256(source_manifest).hexdigest()
    raw_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    # Rebuild to pin the executable to these exact source bytes, rather than
    # trusting timestamps left by an interrupted or concurrent build.
    subprocess.run(["make", "-B", "build/cpp-benchmark"], cwd=root, check=True)
    temporary = Path(tempfile.gettempdir()) / ("queuecraft-native-bench-" + uuid.uuid4().hex)
    command = [str(root / "build/cpp-benchmark"), str(args.input.resolve()), str(temporary), raw_hash, source_tree]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if completed.returncode:
        failure = {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "source_hashes": source_hashes, "input_sha256": raw_hash}
        with failure_output.open("x") as file:
            file.write(json.dumps(failure, indent=2) + "\n")
        raise SystemExit(f"benchmark failed; retained {failure_output}")
    result = json.loads(completed.stdout)
    if result["input_sha256"] != raw_hash or result["source_tree_sha256"] != source_tree:
        raise SystemExit("benchmark identity mismatch")
    current_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source_names}
    if current_hashes != source_hashes or hashlib.sha256(args.input.read_bytes()).hexdigest() != raw_hash:
        with failure_output.open("x") as file:
            file.write(json.dumps({"status": "source_or_data_changed_during_run", "superseded_result": result, "source_hashes_at_start": source_hashes, "source_hashes_at_end": current_hashes}, indent=2) + "\n")
        raise SystemExit(f"source/data changed during measurement; retained {failure_output}")
    result["source_hashes"] = source_hashes
    result["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["platform"] = platform.platform()
    result["python"] = platform.python_version()
    result["compiler"] = subprocess.check_output(["clang++", "--version"], text=True).splitlines()[0]
    result["input_file"] = args.input.name
    result["regression_baseline"] = "initial v0.1.0 implementation; preserve result for later comparisons; no speedup claimed"
    with output.open("x") as file:
        file.write(json.dumps(result, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
