"""An installed consumer. Run outside the repository: python strategy.py input.csv."""
import json
import sys
from pathlib import Path

from queuecraft import Intent, Observation, OrderRequest, Scenario, run
from queuecraft.sdk import events_from_csv


class PatientSlice:
    def decide(self, observation: Observation) -> OrderRequest:
        remaining_time = observation.intent.deadline_ns - observation.now_ns
        size = observation.remaining if remaining_time <= 2_000_000_000 else min(observation.remaining, 1)
        return OrderRequest(size)


if __name__ == "__main__":
    events = events_from_csv(Path(sys.argv[1]).read_text())
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    start = events[0].receive_ns
    result = run(events, Intent("buy", size, start, start + 5_000_000_000), PatientSlice(), Scenario())
    print(json.dumps({"requested": size, "filled": result.filled, "cash": result.cash, "shortfall2": result.shortfall2, "trace": result.fills}, indent=2))
