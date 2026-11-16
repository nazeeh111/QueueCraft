"""Incremental CLI adapter. Only complete writes publish exclusive files."""
from dataclasses import asdict
import json
import os
import sys
import tempfile
from pathlib import Path
from .ingestion import CSVEvents
from .replay import stream
from .sdk import Intent, Scenario
from .policies import POLICIES


def execute(args):
    intent = Intent(args.side, args.size, args.start_ns, args.deadline_ns, args.interval_ns)
    scenario = Scenario(latency_ns=args.latency_ns, observation_delay_ns=args.observation_ns,
                        ack_delay_ns=args.ack_ns, fee_ppm=args.fee_ppm,
                        liquidity_ppm=args.liquidity_ppm, tie=args.tie)
    source = CSVEvents(args.input)
    replay = stream(source, intent, POLICIES[args.policy](), scenario,
                    recording_end_ns=args.recording_end_ns, collect=args.collect,
                    trace_books=args.trace_books, max_pending_events=args.max_pending_events)
    temporary = None
    output = sys.stdout
    try:
        if args.out is not None:
            fd, temporary = tempfile.mkstemp(prefix="."+args.out.name+".", suffix=".tmp", dir=args.out.parent)
            output = os.fdopen(fd, "w", encoding="utf-8")
        def write(record):
            output.write(json.dumps(record, separators=(",", ":"), allow_nan=False)+"\n")
        write({"kind":"configuration", "schema_version":1, "intent":asdict(intent),
               "scenario":asdict(scenario), "policy":args.policy,
               "recording_end_ns":args.recording_end_ns, "collect":args.collect,
               "max_pending_events":args.max_pending_events})
        with replay:
            for record in replay:
                if record["kind"] in {"complete", "incomplete"}:
                    record["input"] = {"sha256":source.sha256, "complete":source.complete,
                                       "bytes_read":source.bytes_read, "events_read":source.events_read}
                write(record)
        output.flush()
        if args.out is not None:
            os.fsync(output.fileno())
            output.close()
            # Atomic exclusive publication: a concurrent existing file wins.
            os.link(temporary, args.out)
        return 0 if replay.status == "complete" else 2
    finally:
        try:
            replay.close()
        finally:
            try:
                if args.out is not None:
                    output.close()
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)
