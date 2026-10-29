# Joint latency and liquidity planning, version 1

This family and algorithm were fixed before evaluating any new real-data policy
outcomes. The prior heuristic is retained as `LegacyHorizon`, registered under
`legacy_horizon`. Its original study remains a prior attempt; it is not silently
recomputed as though the new planner had generated those results.

`RecedingHorizon` now evaluates one common scheduled order plan across a joint
family of hypothetical environments:

| Parameter | Frozen default |
| --- | --- |
| Hypothetical order latency | 0, 1 and 3 seconds |
| Available-liquidity fraction | 10%, 50% and 100% |
| Adverse drift shock | −0.5 and +0.5 observed spreads per decision interval |
| Decision stages | At most four, on the existing integer decision grid |
| Candidate cumulative targets | 0%, 25%, 50%, 75% and 100% of remaining intent |
| Projected price levels | First 16 opposing levels |
| Generic future price bound | At least one tick; optional explicit upper bound |

The immutable typed `PlanningConfig` rejects mutable families, duplicates,
unsorted values and excessive work settings. For the binary-contract study,
`PlanningConfig(max_price_ticks=999)` bounds projected quotes to the declared
instrument range. Generic API calls leave that upper bound unset. A supplied
upper bound must already contain the observed opposing quotes.

The optimizer does **not** read the execution environment's `latency_ns` or
`liquidity_ppm` as hidden ground truth. It knows the declared fee schedule and
its own modeled computation duration. Latency and liquidity inside planning
come from the frozen family. The same scheduled quantities are evaluated under
every combination, so future quantities cannot select a different, favorable
plan using knowledge of the environment. Only the first order is submitted.
The next policy-visible observation causes a new plan.

Each common candidate consists of nonnegative child quantities whose sum is no
greater than the currently unreserved remaining intent. For four stages and
four target quanta there are at most 70 distinct candidates. The default family
has 18 environments. Configuration limits remain four latency values, four
liquidity values, three shocks, four stages and 64 projected levels. The default
worst-case loop bound is 70 × 18 × 4 × 16 level visits before early exits.
These bounds constrain planning work; measured runtime still matters.

Every candidate's child orders arrive after its stage offset, the environment's
latency and the declared computation duration. A late arrival contributes no
fill. Remaining quantity receives the same unfinished-lot penalty as evaluation.
Within each environment, modeled consumption persists across its future IOC
orders and never resets. Availability is the declared fraction of remaining
unconsumed displayed depth. The model retains original price priority.

The price envelope uses only the last five available midpoint observations.
Their signed movement is expressed per decision interval and bounded to one
observed spread in either direction. The configured adverse drift shock is
added. Projected prices retain half-tick precision, using signed integer floor
for time scaling; configured price bounds clamp projections. Hypothetical
per-fill fees use an integer ceiling. Actual fills always use the native engine's
recorded integer tick prices, actual consumed overlay and exact ledger.

The objective is signed implementation shortfall against the current observed
midpoint plus fees and unfinished-lot penalties, represented as twice-money
units. A candidate minimizes the maximum modeled cost. Equal worst costs favor
earlier completion using a fixed lexicographic rule, without consulting future
realized fills. `PlanningDecision` records the selected common plan, time offsets,
every selected-plan environment cost, candidate count and all candidates' worst
costs, allowing a small exhaustive independent check.

This is a finite planning heuristic, not a calibrated guarantee or an optimizer
over all possible execution strategies. It does not forecast depth changes,
new liquidity, acknowledgement-dependent future retries or market impact.
Current recorded depth may include liquidity already consumed by earlier
hypothetical orders, because the policy sees the historical observation book;
the model's fraction family is not an estimate of that identity. Native
execution continues to enforce the actual simulation's consumed overlay.
No environment probabilities, fitted predictor or claim of superiority is used.

`tests/test_planning.py` independently enumerates a hand-sized plan grid, checks
the complete joint objective, demonstrates an action change caused by latency
uncertainty, and distinguishes a common plan from clairvoyant recourse. It also
checks liquidity sensitivity, persistent modeled consumption, exact fee ceilings,
deadline/computation duration, price bounds, fixed work limits and legacy-policy
retention. These are controlled correctness examples, not market results.
