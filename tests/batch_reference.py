"""Frozen eager scheduler oracle from main e467a4954285b45f98aacfeaffb7c01e3543857d.

Test-only reference; retain its scheduling/reducer independently of streaming.
"""
import heapq
from queuecraft.sdk import Book, Intent, Scenario, Simulation, Observation, OrderRequest, _levels, integer, MAX_I64
from typing import Iterable
from queuecraft.sdk import Event, Strategy

def batch_run(events: Iterable[Event], intent: Intent, strategy: Strategy, scenario: Scenario = Scenario(), *, recording_end_ns: int, benchmark2: int | None = None, trace_books: bool = False) -> Simulation:
    """Run deterministic discrete-event simulation, independent of replay speed.

    cancel requests race with pending IOC arrivals at declared modeled latency.
    IOC residual returns to parent intent after acknowledgement. A missing
    decision invokes no-op; it never reruns a strategy on future observations.
    """
    events = tuple(events)
    if not events or events[0].index != 0:
        raise ValueError("events must start at index zero")
    # A recorder's terminal metadata is an input independent of the final book
    # message. Quiet recordings and truncated event prefixes must not reveal a
    # later event's existence through callback/fill/ack eligibility.
    coverage_end = integer(recording_end_ns, "recording_end_ns")
    if intent.start_ns > coverage_end:
        raise ValueError("parent start exceeds declared recording coverage")
    if any(event.receive_ns > coverage_end for event in events):
        raise ValueError("event exceeds declared recording coverage")
    result = Simulation(intent, scenario, type(strategy).__name__, coverage_end)
    book, observed = Book(), Book()
    heap: list[tuple[int, int, int, str, object]] = []
    serial = 0

    def push(t: int, priority: int, kind: str, payload: object) -> None:
        nonlocal serial
        integer(t, "scheduled timestamp")
        serial += 1
        heapq.heappush(heap, (t, priority, serial, kind, payload))

    market_priority = 0 if scenario.tie == "recorded_first" else 2
    arrival_priority = 2 if scenario.tie == "recorded_first" else 0
    for event in events:
        push(event.receive_ns, market_priority, "market", event)
        push(event.receive_ns + scenario.observation_delay_ns, 3, "observe", event)
    # Decision grid never depends on the end of the supplied data prefix.
    for t in range(intent.start_ns, intent.deadline_ns + 1, intent.interval_ns):
        push(t, 4, "decision", None)
    orders: dict[int, dict] = {}
    reserved = acknowledged = 0
    actual = (-1, -1, -1, False, (), ())
    view = actual
    decision_index = 0
    # A common evaluation benchmark can be declared separately from the
    # strategy's visible intent; an evaluation-only reference must not leak
    # a quote still hidden by that strategy's observation delay.
    benchmark_set = benchmark2 is not None
    if benchmark_set:
        result.benchmark2 = integer(benchmark2, "benchmark2", 1)
    checked_cap = False
    fill_serial = 0
    while heap:
        now, _, _, kind, payload = heapq.heappop(heap)
        if kind == "market":
            event = payload
            trace = book.apply(event)
            actual = _levels(trace)
            if trace_books:
                result.book_trace.append(trace)
        elif kind == "observe":
            view = _levels(observed.apply(payload))
        elif kind == "decision":
            eid, ex, recv, valid, bids, asks = view
            stale = recv < 0 or now - recv > scenario.max_staleness_ns
            valid = valid and bool(bids and asks) and not stale and now <= coverage_end
            if valid and not benchmark_set:
                result.benchmark2 = bids[0][0] + asks[0][0]
                benchmark_set = True
            if valid and not checked_cap:
                # One fixed cap, same across all policies/scenarios. Top-ten
                # observed depth excludes no future information.
                depth = min(sum(q for _, q in bids[:10]), sum(q for _, q in asks[:10]))
                if intent.quantity * 1_000_000 > depth * intent.participation_ppm:
                    raise ValueError("order exceeds 1% of initial observed top-ten depth")
                checked_cap = True
            available = max(0, intent.quantity - acknowledged - reserved)
            obs = Observation(now, ex, recv, eid, bids, asks, valid, acknowledged, available, reserved, intent, scenario)
            missed = (scenario.missed_decision_every > 0 and (decision_index + 1) % scenario.missed_decision_every == 0) or scenario.policy_duration_ns > scenario.decision_budget_ns
            req = OrderRequest() if missed or not valid else strategy.decide(obs)
            if not isinstance(req, OrderRequest):
                raise TypeError("strategy must return OrderRequest")
            integer(req.quantity, "requested quantity", 0, available)
            if len(req.cancel) > 10_000:
                raise ValueError("too many cancel requests")
            result.decisions.append({"time_ns": now, "event": eid, "observed_receive_ns": recv, "quantity": req.quantity, "remaining": available, "reserved": reserved, "valid": valid, "fallback": "noop" if missed else "none", "cancel": list(req.cancel)})
            for oid in req.cancel:
                integer(oid, "cancel order ID", 1)
                cancel_latency = scenario.latency_ns if scenario.cancel_latency_ns is None else scenario.cancel_latency_ns
                push(now + scenario.policy_duration_ns + cancel_latency, arrival_priority, "cancel", oid)
            if req.quantity:
                oid = len(orders) + 1
                arrival = now + scenario.policy_duration_ns + scenario.latency_ns
                integer(arrival, "arrival timestamp")
                order = {"order_id": oid, "decision_ns": now, "observation_ns": recv, "arrival_ns": arrival, "ack_ns": arrival + scenario.ack_delay_ns, "quantity": req.quantity, "status": "pending", "filled": 0}
                orders[oid] = order
                reserved += req.quantity
                push(arrival, arrival_priority, "arrival", oid)
            decision_index += 1
        elif kind == "cancel":
            order = orders.get(payload)
            if order and order["status"] == "pending":
                order["status"] = "canceled"
                order["cancel_arrival_ns"] = now
                order["ack_ns"] = now + scenario.ack_delay_ns
                # reservation released only on modeled acknowledgement
                push(now + scenario.ack_delay_ns, 1, "ack", payload)
        elif kind == "arrival":
            order = orders[payload]
            if order["status"] != "pending":
                continue
            eid, ex, recv, valid, _, _ = actual
            order["status"] = "expired"
            if now <= intent.deadline_ns and now <= coverage_end and valid and now - recv <= scenario.max_staleness_ns:
                execution = book.take(intent.side, order["quantity"], fee_ppm=scenario.fee_ppm, liquidity_ppm=scenario.liquidity_ppm)
                order["filled"] = execution["filled"]
                order["status"] = "filled" if execution["remaining"] == 0 else "partial"
                for fill in execution["fills"]:
                    fill_serial += 1
                    result.fills.append({**fill, "fill_id": fill_serial, "order_id": payload, "event": eid, "exchange_ns": ex, "arrival_ns": now, "recorded_receive_ns": recv, "side": intent.side})
                result.cash, result.inventory, result.fees = execution["cash"], execution["inventory"], execution["fees"]
                result.filled += execution["filled"]
            result.ledger.append({"step": len(result.ledger), "order_id": payload, "time_ns": now, "cash": result.cash, "inventory": result.inventory, "fees": result.fees, "filled": result.filled})
            push(order["ack_ns"], 1, "ack", payload)
        elif kind == "ack":
            order = orders[payload]
            if not order.get("acknowledged"):
                reserved -= order["quantity"]
                acknowledged += order["filled"]
                order["acknowledged"] = True
    if not benchmark_set:
        raise ValueError("no valid decision-time benchmark")
    result.orders = list(orders.values())
    result.unfilled = intent.quantity - result.filled
    sign = 1 if intent.side == "buy" else -1
    notional = sum(f["notional"] for f in result.fills)
    result.shortfall2 = sign * (2 * notional - result.filled * result.benchmark2) + 2 * result.fees + 2 * result.unfilled * intent.penalty_ticks
    integer(result.shortfall2, "shortfall2", -MAX_I64-1)
    return result
