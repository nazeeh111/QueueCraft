"""Hand-sized independent checks of the common-plan objective, not native fills."""
from dataclasses import FrozenInstanceError, replace
from itertools import product
import unittest

from queuecraft.policies import (LegacyHorizon, PlanningConfig, POLICIES,
                                RecedingHorizon)
from queuecraft.sdk import Intent, Observation, Scenario

NS = 1_000_000_000


def observation(*, quantity=2, depth=100, side="buy", deadline=2*NS, scenario=None):
    return Observation(0, -1, 0, 0, ((100, depth),), ((104, depth),), True,
                       0, quantity, 0, Intent(side, quantity, 0, deadline),
                       scenario or Scenario())


def independent_one_level_cost(o, plan, offsets, latency, liquidity, shock, cap=None):
    """Scalar oracle written without using planner helpers or optimization."""
    side = 1 if o.intent.side == "buy" else -1
    price, recorded = (o.asks if side == 1 else o.bids)[0]
    mid_twice = o.bids[0][0] + o.asks[0][0]
    spread = o.asks[0][0] - o.bids[0][0]
    used = executed = total = 0
    for stage, requested in enumerate(plan):
        delay = offsets[stage] + latency + o.scenario.policy_duration_ns
        if delay > o.intent.deadline_ns - o.now_ns:
            continue
        available = ((recorded-used)*liquidity)//1_000_000
        amount = min(requested, available)
        movement2 = ((2*spread*shock)//1_000_000)*delay//o.intent.interval_ns
        projected = max(2, 2*price + side*movement2)
        if cap is not None:
            projected = min(projected, 2*cap)
        fee_numerator = amount*projected*o.scenario.fee_ppm
        fee = fee_numerator//2_000_000 + (fee_numerator % 2_000_000 != 0)
        total += side*amount*(projected-mid_twice) + 2*fee
        used += amount
        executed += amount
    return total + (o.remaining-executed)*2*o.intent.penalty_ticks


class PlanningTests(unittest.TestCase):
    def test_configuration_is_frozen_bounded_and_not_execution_truth(self):
        config = PlanningConfig()
        with self.assertRaises(FrozenInstanceError):
            config.stages = 3
        invalid = ({"latencies_ns": [0, NS]}, {"liquidity_ppm": (1_000_001,)},
                   {"latencies_ns": (NS, 0)}, {"latencies_ns": (True,)},
                   {"drift_shocks_ppm": (0, 0)}, {"max_levels": 65},
                   {"stages": 5}, {"split_quanta": 5})
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                PlanningConfig(**values)
        o = observation()
        a = RecedingHorizon(config).plan(o)
        b = RecedingHorizon(config).plan(replace(o, scenario=Scenario(latency_ns=100*NS, liquidity_ppm=0)))
        self.assertEqual(a, b)

    def test_joint_plan_matches_independent_exhaustive_objective(self):
        config = PlanningConfig(latencies_ns=(0, NS), liquidity_ppm=(500_000, 1_000_000),
                                drift_shocks_ppm=(-1_000_000,), stages=2, split_quanta=2)
        o = observation(depth=3)
        decision = RecedingHorizon(config).plan(o)
        # All nonnegative two-order plans totaling <=2, independent enumeration.
        plans = [plan for plan in product(range(3), repeat=2) if sum(plan) <= 2]
        scores = {plan: max(independent_one_level_cost(o, plan, (0, 2*NS), latency, liquidity, -1_000_000)
                           for latency in (0, NS) for liquidity in (500_000, 1_000_000)) for plan in plans}
        expected = min(plans, key=lambda plan: (scores[plan], tuple(-q for q in plan)))
        self.assertEqual(dict(decision.candidate_scores2), scores)
        self.assertEqual(decision.order_plan, expected)
        self.assertEqual(decision.worst_cost2, scores[expected])
        self.assertEqual(decision.candidates_evaluated, len(plans))
        self.assertEqual(len(decision.outcomes), 4)

    def test_latency_uncertainty_changes_action_and_has_no_clairvoyant_recourse(self):
        o = observation()
        common = dict(liquidity_ppm=(1_000_000,), drift_shocks_ppm=(-1_000_000,),
                      stages=2, split_quanta=2)
        known = RecedingHorizon(PlanningConfig(latencies_ns=(0,), **common)).plan(o)
        uncertain = RecedingHorizon(PlanningConfig(latencies_ns=(0, NS), **common)).plan(o)
        self.assertEqual(known.order_plan, (0, 2))
        self.assertEqual(uncertain.order_plan, (2, 0))
        self.assertEqual((known.worst_cost2, uncertain.worst_cost2), (-24, 8))
        plans = [plan for plan in product(range(3), repeat=2) if sum(plan) <= 2]
        clairvoyant = max(min(independent_one_level_cost(o, plan, (0, 2*NS), latency, 1_000_000, -1_000_000)
                             for plan in plans) for latency in (0, NS))
        self.assertEqual(clairvoyant, -8)
        self.assertGreater(uncertain.worst_cost2, clairvoyant)
        self.assertEqual(tuple(x.cost2 for x in uncertain.outcomes), (8, -8))

    def test_liquidity_family_changes_plan_and_never_resets_consumption(self):
        o = observation(depth=3)
        common = dict(latencies_ns=(0,), drift_shocks_ppm=(0,), stages=2, split_quanta=2)
        full = RecedingHorizon(PlanningConfig(liquidity_ppm=(1_000_000,), **common)).plan(o)
        uncertain = RecedingHorizon(PlanningConfig(liquidity_ppm=(500_000, 1_000_000), **common)).plan(o)
        self.assertEqual(full.order_plan, (2, 0))
        self.assertEqual(uncertain.order_plan, (1, 1))
        self.assertTrue(all(x.filled == 2 and x.unfilled == 0 for x in uncertain.outcomes))
        zero = RecedingHorizon(PlanningConfig(liquidity_ppm=(0,), **common)).plan(o)
        self.assertEqual(zero.worst_cost2, 40)
        self.assertEqual(zero.outcomes[0].filled, 0)

    def test_deadline_computation_time_and_exact_fee_ceiling(self):
        o = observation(quantity=1, scenario=Scenario(fee_ppm=1))
        config = PlanningConfig(latencies_ns=(0,), liquidity_ppm=(1_000_000,),
                                drift_shocks_ppm=(0,), stages=1)
        planned = RecedingHorizon(config).plan(o)
        self.assertEqual(planned.worst_cost2, 6)  # two-tick spread cost + one money fee
        expired = RecedingHorizon(config).plan(replace(o, scenario=Scenario(policy_duration_ns=3*NS)))
        self.assertEqual(expired.outcomes[0].unfilled, 1)
        self.assertEqual(expired.worst_cost2, 20)
        grid = RecedingHorizon(replace(config, stages=2)).plan(replace(o, scenario=Scenario(policy_duration_ns=NS)))
        self.assertEqual(grid.decision_offsets_ns, (0, NS))

    def test_forecast_price_bounds_are_declared_and_respected(self):
        o = observation(quantity=1)
        config = PlanningConfig(latencies_ns=(2*NS,), liquidity_ppm=(1_000_000,),
                                drift_shocks_ppm=(1_000_000,), stages=1, max_price_ticks=105)
        result = RecedingHorizon(config).plan(o)
        self.assertEqual(result.worst_cost2, 6)
        with self.assertRaises(ValueError):
            RecedingHorizon(replace(config, max_price_ticks=100)).plan(o)

    def test_work_bound_repeated_inspection_and_prefix_state(self):
        o = observation(quantity=100, deadline=30*NS)
        o = replace(o, asks=tuple((104+i, 1000) for i in range(100)))
        policy = RecedingHorizon()
        result = policy.plan(o)
        self.assertEqual(result.candidates_evaluated, 70)
        self.assertEqual(len(result.outcomes), 18)
        self.assertEqual(result.projected_levels, 16)
        self.assertEqual(policy.plan(o), result)
        self.assertTrue(all(sum(plan) <= o.remaining for plan, _ in result.candidate_scores2))
        # Later observations cannot mutate the frozen diagnostic for this prefix.
        prior = result
        policy.plan(replace(o, now_ns=NS, bids=((200, 1000),), asks=((204, 1000),)))
        self.assertEqual(prior, result)

    def test_sell_objective_and_legacy_attempt_retained(self):
        o = observation(side="sell", scenario=Scenario(fee_ppm=2000))
        config = PlanningConfig(latencies_ns=(0, NS), liquidity_ppm=(500_000,),
                                drift_shocks_ppm=(0,), stages=2, split_quanta=2)
        result = RecedingHorizon(config).plan(o)
        expected = max(independent_one_level_cost(o, result.order_plan, result.decision_offsets_ns,
                                                 latency, 500_000, 0) for latency in (0, NS))
        self.assertEqual(result.worst_cost2, expected)
        self.assertIs(POLICIES["legacy_horizon"], LegacyHorizon)
        self.assertIs(POLICIES["horizon"], RecedingHorizon)


if __name__ == "__main__":
    unittest.main()
