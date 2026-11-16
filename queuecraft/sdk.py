"""Public strategy SDK. Strategies see immutable, delayed prefixes only.

Times are modeled nanoseconds on the supplied capture/receive timeline.
The archive adapter cannot identify exchange timestamps or true network latency.
"""
from __future__ import annotations

import csv
import heapq
import io
from dataclasses import asdict, dataclass, field
from typing import Iterable, Protocol

HEADER = "event,exchange_ns,receive_ns,kind,side,price,quantity\n"
MAX_I64 = 2**63 - 1


def integer(value: int, name: str, low: int = 0, high: int = MAX_I64) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


@dataclass(frozen=True)
class Event:
    index: int
    exchange_ns: int
    receive_ns: int
    kind: str
    levels: tuple[tuple[str, int, int], ...]

    def csv(self) -> str:
        return HEADER + "".join(f"{self.index},{self.exchange_ns},{self.receive_ns},{self.kind},{s},{p},{q}\n" for s, p, q in self.levels)


def events_from_csv(text: str) -> tuple[Event, ...]:
    # Native parser remains the authoritative input validator. This grouping
    # does not discard metadata disagreements or extra columns.
    from . import _native
    _native.validate(text)
    if not text.startswith(HEADER) or len(text.encode()) > 64 * 1024**2:
        raise ValueError("invalid header or input exceeds 64 MiB")
    groups: list[Event] = []
    current: list[tuple[str, int, int]] = []
    key = None
    for row in csv.reader(io.StringIO(text[len(HEADER):])):
        if len(row) != 7:
            raise ValueError("expected seven CSV fields")
        e, x, t, kind, side, p, q = row
        if any(not v or v.strip() != v for v in row):
            raise ValueError("empty field or whitespace")
        newkey = (int(e), int(x), int(t), kind)
        if key is not None and newkey[0] == key[0] and newkey != key:
            raise ValueError("inconsistent event metadata")
        if newkey != key:
            if key is not None:
                groups.append(Event(*key, tuple(current)))
            key, current = newkey, []
        current.append((side, int(p), int(q)))
    if key is not None:
        groups.append(Event(*key, tuple(current)))
    if not groups:
        raise ValueError("empty input")
    return tuple(groups)


class Book:
    """One native single-writer state machine per independent simulation."""

    def __init__(self) -> None:
        from . import _native
        self._native = _native
        self._handle = _native.create()

    def apply(self, event: Event) -> str:
        return self._native.apply(self._handle, event.csv())

    def trace(self) -> str:
        return self._native.snapshot(self._handle)

    def take(self, side: str, quantity: int, *, fee_ppm: int = 0, liquidity_ppm: int = 1_000_000) -> dict:
        return self._native.take(self._handle, side, quantity, fee_ppm, liquidity_ppm)


@dataclass(frozen=True)
class Intent:
    side: str
    quantity: int
    start_ns: int
    deadline_ns: int
    interval_ns: int = 1_000_000_000
    penalty_ticks: int = 10
    max_quantity: int = 100_000_000
    participation_ppm: int = 10_000

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        for name in ("quantity", "interval_ns", "max_quantity"):
            integer(getattr(self, name), name, 1)
        integer(self.start_ns, "start_ns")
        integer(self.deadline_ns, "deadline_ns", self.start_ns)
        integer(self.penalty_ticks, "penalty_ticks")
        integer(self.participation_ppm, "participation_ppm", 1, 10_000)
        if self.quantity > self.max_quantity:
            raise ValueError("quantity exceeds declared small-order cap")
        if (self.deadline_ns - self.start_ns) // self.interval_ns > 100_000:
            raise ValueError("too many decision times")


@dataclass(frozen=True)
class Scenario:
    latency_ns: int = 0
    observation_delay_ns: int = 0
    ack_delay_ns: int = 0
    liquidity_ppm: int = 1_000_000
    fee_ppm: int = 0
    max_staleness_ns: int = 2_000_000_000
    tie: str = "recorded_first"
    missed_decision_every: int = 0
    cancel_latency_ns: int | None = None
    policy_duration_ns: int = 0
    decision_budget_ns: int = 1_000_000_000

    def __post_init__(self) -> None:
        for name in ("latency_ns", "observation_delay_ns", "ack_delay_ns", "fee_ppm", "max_staleness_ns", "missed_decision_every", "policy_duration_ns", "decision_budget_ns"):
            integer(getattr(self, name), name)
        if self.cancel_latency_ns is not None:
            integer(self.cancel_latency_ns, "cancel_latency_ns")
        integer(self.liquidity_ppm, "liquidity_ppm", 0, 1_000_000)
        if self.fee_ppm > 1_000_000 or self.tie not in {"recorded_first", "arrival_first"}:
            raise ValueError("invalid fee or tie assumption")


@dataclass(frozen=True)
class Observation:
    now_ns: int
    exchange_ns: int
    observed_receive_ns: int
    event: int
    bids: tuple[tuple[int, int], ...]
    asks: tuple[tuple[int, int], ...]
    valid: bool
    acknowledged_filled: int
    remaining: int
    reserved: int
    intent: Intent
    scenario: Scenario


@dataclass(frozen=True)
class OrderRequest:
    quantity: int = 0
    cancel: tuple[int, ...] = ()


class Strategy(Protocol):
    def decide(self, observation: Observation) -> OrderRequest: ...


@dataclass
class Simulation:
    intent: Intent
    scenario: Scenario
    policy: str
    recording_end_ns: int
    decisions: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)
    ledger: list[dict] = field(default_factory=list)
    book_trace: list[str] = field(default_factory=list)
    benchmark2: int = 0
    filled: int = 0
    unfilled: int = 0
    cash: int = 0
    inventory: int = 0
    fees: int = 0
    shortfall2: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _levels(trace: str) -> tuple[int, int, int, bool, tuple, tuple]:
    rows = list(csv.DictReader(io.StringIO(trace)))
    if not rows:
        return -1, -1, -1, False, (), ()
    row = rows[0]
    bids = tuple(sorted(((int(r["price"]), int(r["quantity"])) for r in rows if r["side"] == "B"), reverse=True))
    asks = tuple(sorted((int(r["price"]), int(r["quantity"])) for r in rows if r["side"] == "A"))
    return int(row["event"]), int(row["exchange_ns"]), int(row["receive_ns"]), row["valid"] == "1", bids, asks


def run(events: Iterable[Event], intent: Intent, strategy: Strategy, scenario: Scenario = Scenario(), *, recording_end_ns: int, benchmark2: int | None = None, trace_books: bool = False) -> Simulation:
    """Collect a complete incremental replay; errors never return a partial result."""
    from .replay import stream
    replay = stream(events, intent, strategy, scenario, recording_end_ns=recording_end_ns,
                    benchmark2=benchmark2, trace_books=trace_books, collect=True,
                    max_pending_events=None)
    for _ in replay:
        pass
    if replay.exception is not None:
        raise replay.exception
    return replay.result
