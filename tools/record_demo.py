"""Record real installed CLI executions as an asciinema v2 cast. No fake typing."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True, help="independently installed environment")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh evidence directory")
    args = parser.parse_args()
    python = str(args.python.absolute())  # Preserve the virtual-environment executable path.
    source = args.source.resolve()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for original, name in (("examples/recorded.csv", "input.csv"),
                           ("examples/recorded-provenance.json", "recording.json"),
                           ("examples/strategy.py", "strategy.py")):
        shutil.copyfile(source / original, root / name)
    commands = [
        [python, "-c", "import queuecraft; print(queuecraft.__file__)"],
        [python, "-m", "queuecraft", "validate", "input.csv"],
        [python, "-m", "queuecraft", "simulate", "input.csv", "--size", "25", "--policy", "twap",
         "--recording-metadata", "recording.json", "--out", "order25"],
        [python, "-m", "queuecraft", "verify", "order25"],
        [python, "-m", "queuecraft", "simulate", "input.csv", "--size", "50", "--policy", "twap",
         "--recording-metadata", "recording.json", "--out", "order50"],
        [python, "-m", "queuecraft", "verify", "order50"],
        [python, "strategy.py", "input.csv", "7"],
    ]
    results = []
    start = time.perf_counter()
    with (root / "demo.cast").open("x") as cast:
        cast.write(json.dumps({"version": 2, "width": 110, "height": 32,
                               "timestamp": int(time.time()), "title": "QueueCraft: installed execution and changed order",
                               "env": {"TERM": "xterm-256color"}}) + "\n")

        def emit(content):
            cast.write(json.dumps([time.perf_counter() - start, "o", content.replace("\n", "\r\n")]) + "\n")
            cast.flush()

        for command in commands:
            emit("$ " + shlex.join(command) + "\n")
            before = time.perf_counter()
            result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            emit(result.stdout)
            results.append({"argv": command, "exit_code": result.returncode,
                            "elapsed_seconds": time.perf_counter() - before, "output": result.stdout})
            if result.returncode:
                raise RuntimeError(f"demo command failed: {shlex.join(command)}")
    traces = [json.loads((root / name / "result.json").read_text()) for name in ("order25", "order50")]
    if traces[0]["fills"] == traces[1]["fills"] or traces[0]["cash"] == traces[1]["cash"]:
        raise RuntimeError("changed order did not produce distinct traces and account deltas")
    record = {"status": "pass", "commands": results, "duration_seconds": time.perf_counter() - start,
              "input_sha256": hashlib.sha256((root / "input.csv").read_bytes()).hexdigest(),
              "cast_sha256": hashlib.sha256((root / "demo.cast").read_bytes()).hexdigest(),
              "changed_input_distinct": True, "scripted_commands_real_output": True}
    (root / "demo-execution.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({key: value for key, value in record.items() if key != "commands"}, indent=2))


if __name__ == "__main__":
    main()
