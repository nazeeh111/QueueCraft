"""Registered causal policies. No fitted model or future-price access."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations_with_replacement, product
from math import ceil
from statistics import median

from .sdk import Observation, OrderRequest, integer


class Immediate:
    def decide(self, o: Observation) -> OrderRequest:
        return OrderRequest(o.remaining)


class TWAP:
    """Equal parent slices over decision times whose modeled arrivals fit."""
    def decide(self, o: Observation) -> OrderRequest:
        last = o.intent.deadline_ns - o.scenario.latency_ns - o.scenario.policy_duration_ns
        total = max(1, (last - o.intent.start_ns) // o.intent.interval_ns + 1)
        elapsed = min(total, (o.now_ns - o.intent.start_ns) // o.intent.interval_ns + 1)
        target = (o.intent.quantity * elapsed + total - 1) // total
        return OrderRequest(min(o.remaining, max(0, target - o.acknowledged_filled - o.reserved)))


class LiquidityAware:
    """Slice faster at at-least-median observed spread; force near deadline."""
    def __init__(self) -> None:
        self.spreads: list[int] = []

    def decide(self, o: Observation) -> OrderRequest:
        spread = o.asks[0][0] - o.bids[0][0]
        self.spreads.append(spread)
        self.spreads = self.spreads[-30:]
        left = o.intent.deadline_ns - o.scenario.latency_ns - o.scenario.policy_duration_ns - o.now_ns
        if left < o.intent.interval_ns:
            return OrderRequest(o.remaining)
        schedule = TWAP().decide(o).quantity
        return OrderRequest(min(o.remaining, schedule * 2) if spread <= median(self.spreads[-30:]) else 0)


class LegacyHorizon:
    """Finite, prefix-only minimax cost-to-go across depth and drift scenarios.

    Recomputes a four-stage integer inventory plan. The worst case objective
    uses observed depth, trailing midpoint drift, fees, and the same residual
    penalty as evaluation. It is sensitivity to hypothetical scenarios, not
    a calibrated robustness guarantee. No predictor is trained on holdout.
    """
    def __init__(self) -> None:
        self.mids: list[int] = []

    def decide(self, o: Observation) -> OrderRequest:
        if not o.remaining:
            return OrderRequest()
        self.mids.append(o.bids[0][0] + o.asks[0][0])
        self.mids = self.mids[-5:]
        slots = max(0, (o.intent.deadline_ns - o.scenario.latency_ns - o.scenario.policy_duration_ns - o.now_ns) // o.intent.interval_ns)
        if slots == 0:
            return OrderRequest(o.remaining)
        levels = o.asks if o.intent.side == "buy" else o.bids
        sign = 1 if o.intent.side == "buy" else -1
        # Midpoint drift in ticks, bounded to the current spread. Prefix only.
        history = self.mids[-5:]
        drift = sign * (history[-1] - history[0]) / (2 * max(1, len(history) - 1))
        spread = o.asks[0][0] - o.bids[0][0]
        drift = max(-spread, min(spread, drift))
        actions = sorted({0, ceil(o.remaining / 4), ceil(o.remaining / 2), o.remaining})
        horizon = min(4, slots + 1)
        spacing = max(1, slots / max(1, horizon - 1))
        benchmark2 = o.bids[0][0] + o.asks[0][0]

        def cost(q: int, depth_ppm: int, stage: int, shock: float) -> float:
            left, total = q, 0.0
            for price, depth in levels:
                fill = min(left, depth * depth_ppm // 1_000_000)
                total += fill * (sign * (price - benchmark2 / 2) + price * o.scenario.fee_ppm / 1_000_000 + stage * spacing * shock)
                left -= fill
                if not left:
                    break
            return total

        # DP for each assumed environment and first action. Conservative depth
        # available again later is an explicitly hypothetical planning model;
        # actual execution still obeys the native consumed-liquidity overlay.
        scores = {action: [] for action in actions}
        for depth_ppm in (250_000, 500_000, 1_000_000):
            for shock in (drift - spread / 2, drift + spread / 2):
                from functools import lru_cache

                @lru_cache(None)
                def future(remaining: int, stage: int) -> float:
                    if stage >= horizon:
                        return remaining * o.intent.penalty_ticks
                    choices = {0, ceil(remaining / 4), ceil(remaining / 2), remaining}
                    capacity = sum(q * depth_ppm // 1_000_000 for _, q in levels)
                    return min(cost(q, depth_ppm, stage, shock) + future(remaining - min(q, capacity), stage + 1) for q in choices)

                capacity = sum(q * depth_ppm // 1_000_000 for _, q in levels)
                for action in actions:
                    scores[action].append(cost(action, depth_ppm, 0, shock) + future(o.remaining - min(action, capacity), 1))
        chosen = min(actions, key=lambda a: (max(scores[a]), -a))
        return OrderRequest(chosen)


@dataclass(frozen=True)
class PlanningConfig:
    """Frozen, hypothetical environments; no fitted probabilities or guarantee.

    A drift shock is an adverse price movement in millionths of the observed
    spread per decision interval. Latency and available-liquidity assumptions
    are independent of the configured environment used to execute the order.
    """

    latencies_ns: tuple[int, ...] = (0, 1_000_000_000, 3_000_000_000)
    liquidity_ppm: tuple[int, ...] = (100_000, 500_000, 1_000_000)
    drift_shocks_ppm: tuple[int, ...] = (-500_000, 500_000)
    stages: int = 4
    split_quanta: int = 4
    max_levels: int = 16
    max_price_ticks: int | None = None

    def __post_init__(self) -> None:
        for name, low, high, count in (
            ("latencies_ns", 0, 2**63-1, 4),
            ("liquidity_ppm", 0, 1_000_000, 4),
            ("drift_shocks_ppm", -1_000_000, 1_000_000, 3),
        ):
            values = getattr(self, name)
            if type(values) is not tuple or not 1 <= len(values) <= count:
                raise ValueError(f"{name} must be an immutable tuple of 1..{count} values")
            for value in values:
                integer(value, name, low, high)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must contain sorted distinct values")
        integer(self.stages, "stages", 1, 4)
        integer(self.split_quanta, "split_quanta", 1, 4)
        integer(self.max_levels, "max_levels", 1, 64)
        if self.max_price_ticks is not None:
            integer(self.max_price_ticks, "max_price_ticks", 1)


@dataclass(frozen=True)
class PlanningOutcome:
    latency_ns: int
    liquidity_ppm: int
    drift_shock_ppm: int
    cost2: int
    filled: int
    unfilled: int


@dataclass(frozen=True)
class PlanningDecision:
    quantity: int
    order_plan: tuple[int, ...]
    decision_offsets_ns: tuple[int, ...]
    worst_cost2: int
    outcomes: tuple[PlanningOutcome, ...]
    candidates_evaluated: int
    projected_levels: int
    # Every candidate's worst-case value permits independent small-grid checks.
    candidate_scores2: tuple[tuple[tuple[int, ...], int], ...]


class RecedingHorizon:
    """Minimize worst modeled cost over a common, bounded future order plan.

    Every latency/liquidity/drift environment receives the SAME scheduled
    quantities. Future actions cannot optimize with knowledge of which hidden
    environment applies. Only the first quantity is submitted; the next
    observation starts another optimization. This remains a planning heuristic,
    not a calibrated robustness bound or an exact forecast of historical fills.
    """

    def __init__(self, config: PlanningConfig = PlanningConfig()) -> None:
        if not isinstance(config, PlanningConfig):
            raise TypeError("config must be PlanningConfig")
        self.config = config
        self._history: list[tuple[int, int]] = []
        self.last_plan: PlanningDecision | None = None

    def _offsets(self, o: Observation) -> tuple[int, ...]:
        # Network latency is unknown inside planning. Feasibility is evaluated
        # for EACH configured latency after defining this shared decision grid.
        remaining_ns = o.intent.deadline_ns - o.now_ns - o.scenario.policy_duration_ns
        if remaining_ns < 0:
            return (0,)
        slots = remaining_ns // o.intent.interval_ns
        stages = min(self.config.stages, slots + 1)
        if stages == 1:
            return (0,)
        return tuple((index * slots // (stages - 1)) * o.intent.interval_ns for index in range(stages))

    def _plans(self, remaining: int, stages: int) -> tuple[tuple[int, ...], ...]:
        quantum = self.config.split_quanta
        plans = set()
        # Nondecreasing cumulative targets yield common nonnegative order
        # quantities with total <= remaining, including deliberate noncompletion.
        for fractions in combinations_with_replacement(range(quantum + 1), stages):
            cumulative = tuple((remaining * fraction + quantum - 1) // quantum for fraction in fractions)
            previous = 0
            quantities = []
            for target in cumulative:
                quantities.append(target - previous)
                previous = target
            plans.add(tuple(quantities))
        return tuple(sorted(plans))

    def _outcome(
        self, o: Observation, levels: tuple[tuple[int, int], ...],
        offsets: tuple[int, ...], plan: tuple[int, ...],
        latency: int, liquidity: int, shock: int, trend2: int,
    ) -> PlanningOutcome:
        sign = 1 if o.intent.side == "buy" else -1
        benchmark2 = o.bids[0][0] + o.asks[0][0]
        spread = o.asks[0][0] - o.bids[0][0]
        # trend2 is signed adverse midpoint movement in twice ticks/interval.
        # Integer floor is explicit for signed forecast shifts. Half-tick model
        # prices retain midpoint precision; actual fills still use native ticks.
        rate2 = trend2 + (2 * spread * shock // 1_000_000)
        consumed = [0] * len(levels)
        cost2 = filled = 0
        for offset, requested in zip(offsets, plan):
            arrival_delay = offset + o.scenario.policy_duration_ns + latency
            if o.now_ns + arrival_delay > o.intent.deadline_ns:
                continue
            left = requested
            if not left:
                continue
            shift2 = rate2 * arrival_delay // o.intent.interval_ns
            for index, (price, depth) in enumerate(levels):
                available = (depth - consumed[index]) * liquidity // 1_000_000
                quantity = min(left, available)
                if not quantity:
                    continue
                projected_price2 = max(2, 2 * price + sign * shift2)
                if self.config.max_price_ticks is not None:
                    projected_price2 = min(projected_price2, 2 * self.config.max_price_ticks)
                notional2 = quantity * projected_price2
                fee = (notional2 * o.scenario.fee_ppm + 1_999_999) // 2_000_000
                cost2 += sign * quantity * (projected_price2 - benchmark2) + 2 * fee
                filled += quantity
                consumed[index] += quantity
                left -= quantity
                if not left:
                    break
        unfilled = o.remaining - filled
        cost2 += 2 * unfilled * o.intent.penalty_ticks
        return PlanningOutcome(latency, liquidity, shock, cost2, filled, unfilled)

    def plan(self, o: Observation) -> PlanningDecision:
        integer(o.remaining, "remaining", 0, o.intent.quantity)
        if not o.valid or not o.bids or not o.asks or not o.remaining:
            return PlanningDecision(0, (), (), 0, (), 0, 0, ())
        mid2 = o.bids[0][0] + o.asks[0][0]
        # Repeated inspection of the same decision does not change its history.
        if self._history and self._history[-1][0] == o.now_ns:
            self._history[-1] = (o.now_ns, mid2)
        else:
            self._history.append((o.now_ns, mid2))
        self._history = self._history[-5:]
        spread = o.asks[0][0] - o.bids[0][0]
        elapsed = self._history[-1][0] - self._history[0][0]
        sign = 1 if o.intent.side == "buy" else -1
        trend2 = 0 if elapsed <= 0 else sign * (mid2 - self._history[0][1]) * o.intent.interval_ns // elapsed
        trend2 = max(-2 * spread, min(2 * spread, trend2))
        levels = (o.asks if o.intent.side == "buy" else o.bids)[:self.config.max_levels]
        if self.config.max_price_ticks is not None and any(price > self.config.max_price_ticks for price, _ in levels):
            raise ValueError("observed prices exceed the configured planning price cap")
        offsets = self._offsets(o)
        plans = self._plans(o.remaining, len(offsets))
        environments = tuple(product(self.config.latencies_ns, self.config.liquidity_ppm, self.config.drift_shocks_ppm))
        candidates = []
        best_key = None
        best_plan = ()
        best_outcomes = ()
        for candidate in plans:
            outcomes = tuple(self._outcome(o, levels, offsets, candidate, latency, liquidity, shock, trend2)
                             for latency, liquidity, shock in environments)
            worst = max(outcome.cost2 for outcome in outcomes)
            candidates.append((candidate, worst))
            # Equal worst values favor earlier scheduled completion without
            # observing any subsequent realized fill or choosing a favorable tie.
            key = (worst, tuple(-quantity for quantity in candidate))
            if best_key is None or key < best_key:
                best_key, best_plan, best_outcomes = key, candidate, outcomes
        assert best_key is not None
        return PlanningDecision(best_plan[0], best_plan, offsets, best_key[0], best_outcomes,
                                len(candidates), len(levels), tuple(candidates))

    def decide(self, o: Observation) -> OrderRequest:
        self.last_plan = self.plan(o)
        return OrderRequest(self.last_plan.quantity)


POLICIES = {"immediate": Immediate, "twap": TWAP, "liquidity": LiquidityAware,
            "legacy_horizon": LegacyHorizon, "horizon": RecedingHorizon}
