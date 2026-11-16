"""Incremental deterministic merge; one source owner and detached transition records."""
from __future__ import annotations

from copy import deepcopy
import heapq
from itertools import islice
from threading import get_ident

from .sdk import (Book, Event, Intent, Observation, OrderRequest, Scenario,
                  Simulation, Strategy, _levels, integer, MAX_I64)

MAX_EVENT_ROWS = 20_000


def _freeze(event, previous, coverage_end, delay):
    if not isinstance(event, Event):
        raise TypeError("source must yield Event values")
    integer(event.index, "event index")
    integer(event.receive_ns, "event receive timestamp")
    integer(event.exchange_ns, "event exchange timestamp", -1)
    if event.index != (previous[0] + 1 if previous is not None else 0):
        raise ValueError("event indices must be contiguous from zero")
    if previous is not None and event.receive_ns < previous[1]:
        raise ValueError("receive timestamp regressed")
    if event.receive_ns > coverage_end:
        raise ValueError("event exceeds declared recording coverage")
    integer(event.receive_ns + delay, "observation timestamp")
    rows = []
    for row in event.levels:
        if len(rows) == MAX_EVENT_ROWS:
            raise ValueError("event exceeds native row bound")
        fields = tuple(islice(iter(row), 4))
        if len(fields) != 3 or type(fields[0]) is not str or len(fields[0]) != 1:
            raise ValueError("each event level requires side, price and quantity")
        integer(fields[1], "level price", 1)
        integer(fields[2], "level quantity")
        rows.append(fields)
    if type(event.kind) is not str or len(event.kind) != 1 or not rows:
        raise ValueError("invalid event kind or empty levels")
    # Native apply remains authoritative for semantic validation and book state.
    return Event(event.index, event.exchange_ns, event.receive_ns, event.kind, tuple(rows))


class ReplayStream:
    """Iterate provisional transitions; only the terminal complete result is final.

    Default collection is off. Pending input/runtime events have a declared cap;
    an overfull delay/tie window refuses rather than dropping or reordering data.
    Use this iterator in one thread and close it when stopping consumption early.
    """
    def __init__(self, events, intent, strategy, scenario=Scenario(), *, recording_end_ns,
                 benchmark2=None, trace_books=False, collect=False, max_pending_events=100_000):
        self.coverage_end = integer(recording_end_ns, "recording_end_ns")
        if intent.start_ns > self.coverage_end:
            raise ValueError("parent start exceeds declared recording coverage")
        if max_pending_events is not None:
            integer(max_pending_events, "max_pending_events", 1, 10_000_000)
        if type(collect) is not bool or type(trace_books) is not bool:
            raise ValueError("collect and trace_books must be boolean")
        if benchmark2 is not None:
            integer(benchmark2, "benchmark2", 1)
        self.intent, self.scenario, self.strategy = intent, scenario, strategy
        self.collect, self.trace_books, self.max_pending_events = collect, trace_books, max_pending_events
        self.status, self.result, self.exception = "ready", None, None
        self.stats = {"source_events": 0, "transitions": 0, "peak_pending_events": 0,
                      "peak_pending_observations": 0, "peak_active_orders": 0,
                      "source_lookahead": 1, "collected": collect}
        self._source_closed = False
        self._owner = None
        self._source = iter(events)
        self._generator = self._execute(benchmark2)

    def __iter__(self):
        return self

    def __next__(self):
        if self._owner is None:
            self._owner = get_ident()
        if get_ident() != self._owner:
            raise RuntimeError("ReplayStream belongs to its consuming thread")
        return next(self._generator)

    def close(self):
        if self._owner is not None and get_ident() != self._owner:
            raise RuntimeError("ReplayStream belongs to its consuming thread")
        self._generator.close()
        self._close_source()
        if self.status not in {"complete", "incomplete"}:
            self.status = "closed"

    def _close_source(self):
        if not self._source_closed:
            self._source_closed = True
            close = getattr(self._source, "close", None)
            if close is not None:
                close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _execute(self, benchmark2):
        self.status = "running"
        result = Simulation(self.intent, self.scenario, type(self.strategy).__name__, self.coverage_end)
        scenario, intent = self.scenario, self.intent
        heap = []
        serial = pending_observations = 0
        previous = None
        orders, collected_orders = {}, {}
        order_serial = ledger_serial = fill_serial = notional_total = 0
        reserved = acknowledged = decision_index = 0
        actual = view = (-1, -1, -1, False, (), ())
        benchmark_set = benchmark2 is not None
        if benchmark_set:
            result.benchmark2 = benchmark2
        checked_cap = False
        market_priority = 0 if scenario.tie == "recorded_first" else 2
        arrival_priority = 2 if scenario.tie == "recorded_first" else 0

        def read_next():
            nonlocal previous
            try:
                event = next(self._source)
            except StopIteration:
                return None
            event = _freeze(event, previous, self.coverage_end, scenario.observation_delay_ns)
            previous = event.index, event.receive_ns
            self.stats["source_events"] += 1
            return event

        def push(t, priority, kind, payload):
            nonlocal serial, pending_observations
            integer(t, "scheduled timestamp")
            if self.max_pending_events is not None and len(heap) >= self.max_pending_events:
                raise ValueError("pending-event limit reached; increase the declared delay/tie-window budget")
            serial += 1
            heapq.heappush(heap, (t, priority, serial, kind, payload))
            if kind == "observe":
                pending_observations += 1
            self.stats["peak_pending_events"] = max(self.stats["peak_pending_events"], len(heap))
            self.stats["peak_pending_observations"] = max(self.stats["peak_pending_observations"], pending_observations)

        try:
            book, observed = Book(), Book()
            head = read_next()
            if head is None:
                raise ValueError("events must start at index zero")
            decision_time = intent.start_ns
            while head is not None or decision_time is not None or heap:
                candidates = []
                if head is not None:
                    candidates.append((head.receive_ns, market_priority, "market"))
                if decision_time is not None:
                    candidates.append((decision_time, 4, "decision"))
                if heap:
                    candidates.append((heap[0][0], heap[0][1], "pending"))
                now, priority, origin = min(candidates)
                if origin == "market":
                    kind, payload = "market", head
                elif origin == "decision":
                    kind, payload = "decision", None
                    following = decision_time + intent.interval_ns
                    decision_time = following if following <= intent.deadline_ns else None
                else:
                    now, priority, _, kind, payload = heapq.heappop(heap)
                    if kind == "observe":
                        pending_observations -= 1
                data = {}
                if kind == "market":
                    trace = book.apply(payload)
                    actual = _levels(trace)
                    data = {"event": payload.index}
                    if self.trace_books:
                        data["trace"] = trace
                        if self.collect:
                            result.book_trace.append(trace)
                    push(payload.receive_ns + scenario.observation_delay_ns, 3, "observe", payload)
                    head = read_next()
                elif kind == "observe":
                    view = _levels(observed.apply(payload))
                    data = {"event": payload.index}
                elif kind == "decision":
                    eid, ex, recv, valid, bids, asks = view
                    stale = recv < 0 or now - recv > scenario.max_staleness_ns
                    valid = valid and bool(bids and asks) and not stale and now <= self.coverage_end
                    if valid and not benchmark_set:
                        result.benchmark2 = bids[0][0] + asks[0][0]
                        benchmark_set = True
                    if valid and not checked_cap:
                        depth = min(sum(q for _, q in bids[:10]), sum(q for _, q in asks[:10]))
                        if intent.quantity * 1_000_000 > depth * intent.participation_ppm:
                            raise ValueError("order exceeds 1% of initial observed top-ten depth")
                        checked_cap = True
                    available = max(0, intent.quantity - acknowledged - reserved)
                    obs = Observation(now, ex, recv, eid, bids, asks, valid, acknowledged, available, reserved, intent, scenario)
                    missed = (scenario.missed_decision_every > 0 and (decision_index + 1) % scenario.missed_decision_every == 0) or scenario.policy_duration_ns > scenario.decision_budget_ns
                    req = OrderRequest() if missed or not valid else self.strategy.decide(obs)
                    if not isinstance(req, OrderRequest):
                        raise TypeError("strategy must return OrderRequest")
                    integer(req.quantity, "requested quantity", 0, available)
                    if len(req.cancel) > 10_000:
                        raise ValueError("too many cancel requests")
                    data = {"time_ns": now, "event": eid, "observed_receive_ns": recv, "quantity": req.quantity,
                            "remaining": available, "reserved": reserved, "valid": valid,
                            "fallback": "noop" if missed else "none", "cancel": list(req.cancel)}
                    if self.collect:
                        result.decisions.append(deepcopy(data))
                    for oid in req.cancel:
                        integer(oid, "cancel order ID", 1)
                        cancel_latency = scenario.latency_ns if scenario.cancel_latency_ns is None else scenario.cancel_latency_ns
                        push(now + scenario.policy_duration_ns + cancel_latency, arrival_priority, "cancel", oid)
                    if req.quantity:
                        order_serial += 1
                        arrival = now + scenario.policy_duration_ns + scenario.latency_ns
                        integer(arrival, "arrival timestamp")
                        order = {"order_id": order_serial, "decision_ns": now, "observation_ns": recv, "arrival_ns": arrival,
                                 "ack_ns": arrival + scenario.ack_delay_ns, "quantity": req.quantity, "status": "pending", "filled": 0}
                        orders[order_serial] = order
                        if self.collect:
                            collected_orders[order_serial] = order
                        reserved += req.quantity
                        push(arrival, arrival_priority, "arrival", order_serial)
                        self.stats["peak_active_orders"] = max(self.stats["peak_active_orders"], len(orders))
                    decision_index += 1
                elif kind == "cancel":
                    order = orders.get(payload)
                    if order and order["status"] == "pending":
                        order["status"] = "canceled"
                        order["cancel_arrival_ns"] = now
                        order["ack_ns"] = now + scenario.ack_delay_ns
                        push(now + scenario.ack_delay_ns, 1, "ack", payload)
                    data = {"order_id": payload, "order": order}
                elif kind == "arrival":
                    order = orders.get(payload)
                    if order is None or order["status"] != "pending":
                        data = {"order_id": payload, "skipped": True}
                    else:
                        eid, ex, recv, valid, _, _ = actual
                        order["status"] = "expired"
                        fills = []
                        if now <= intent.deadline_ns and now <= self.coverage_end and valid and now - recv <= scenario.max_staleness_ns:
                            execution = book.take(intent.side, order["quantity"], fee_ppm=scenario.fee_ppm, liquidity_ppm=scenario.liquidity_ppm)
                            order["filled"] = execution["filled"]
                            order["status"] = "filled" if execution["remaining"] == 0 else "partial"
                            for fill in execution["fills"]:
                                fill_serial += 1
                                row = {**fill, "fill_id": fill_serial, "order_id": payload, "event": eid, "exchange_ns": ex,
                                       "arrival_ns": now, "recorded_receive_ns": recv, "side": intent.side}
                                fills.append(row)
                                notional_total += fill["notional"]
                                if self.collect:
                                    result.fills.append(row.copy())
                            result.cash, result.inventory, result.fees = execution["cash"], execution["inventory"], execution["fees"]
                            result.filled += execution["filled"]
                        ledger = {"step": ledger_serial, "order_id": payload, "time_ns": now, "cash": result.cash,
                                  "inventory": result.inventory, "fees": result.fees, "filled": result.filled}
                        ledger_serial += 1
                        if self.collect:
                            result.ledger.append(ledger.copy())
                        push(order["ack_ns"], 1, "ack", payload)
                        data = {"order_id": payload, "order": order, "fills": fills, "ledger": ledger}
                elif kind == "ack":
                    order = orders.get(payload)
                    if order and not order.get("acknowledged"):
                        reserved -= order["quantity"]
                        acknowledged += order["filled"]
                        order["acknowledged"] = True
                        orders.pop(payload)
                    data = {"order_id": payload, "order": order}
                self.stats["transitions"] += 1
                yield {"kind": kind, "time_ns": now, "priority": priority, "data": deepcopy(data)}
            if not benchmark_set:
                raise ValueError("no valid decision-time benchmark")
            result.orders = list(collected_orders.values())
            result.unfilled = intent.quantity - result.filled
            sign = 1 if intent.side == "buy" else -1
            result.shortfall2 = sign * (2 * notional_total - result.filled * result.benchmark2) + 2 * result.fees + 2 * result.unfilled * intent.penalty_ticks
            integer(result.shortfall2, "shortfall2", -MAX_I64-1)
            self._close_source()
            self.result, self.status = result, "complete"
            yield {"kind": "complete", "collected": self.collect, "result": result.as_dict(), "stats": self.stats.copy()}
        except GeneratorExit:
            if self.status not in {"complete", "incomplete"}:
                self.status = "closed"
            raise
        except Exception as error:
            try:
                self._close_source()
            except Exception:
                pass  # Preserve the original replay failure.
            self.exception, self.status = error, "incomplete"
            yield {"kind": "incomplete", "error": {"type": type(error).__name__, "message": str(error)},
                   "collected": self.collect, "stats": self.stats.copy()}
        finally:
            self._close_source()


def stream(events, intent: Intent, strategy: Strategy, scenario: Scenario = Scenario(), **options) -> ReplayStream:
    return ReplayStream(events, intent, strategy, scenario, **options)
