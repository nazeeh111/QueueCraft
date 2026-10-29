"""Registered causal policies. No fitted model or future-price access."""
from __future__ import annotations

from math import ceil
from statistics import median

from .sdk import Observation, OrderRequest


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


class RecedingHorizon:
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


POLICIES = {"immediate": Immediate, "twap": TWAP, "liquidity": LiquidityAware, "horizon": RecedingHorizon}
