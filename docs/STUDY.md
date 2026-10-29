# Registered 15-minute study

The registered run completed 66,720 simulations. Independent recomputation
matched every attempt, book-source/timing/accounting check, all 209 DuckDB
window batches and all 480 paired comparison cells. The new horizon policy's
lower penalized cost comes with substantially worse completion. It is not an
execution-superiority or profitability result.

## Data and design

PolyOrderbooks' frozen, CC BY 4.0 archive contains randomly sampled resolved
15-minute binary contracts across eight crypto assets and four capture dates.
This is snapshot data, not a complete exchange event feed. Only Up-token quotes
enter the simulation; resolution/winner labels are excluded. Each contract is
one window, not an independent market day. [Attribution](../data/15m-archive/README.md).

Whole opening UTC dates were reserved before eligibility. The prefix quote/depth
stress proxy is spread >10 ticks or minimum bid/ask top-ten depth below 44,592
lots, the development lower quartile. It is not an external crisis label.

| Opening UTC day | Region | Attempted windows | Valid parent prefix | Ordinary | Stress |
| --- | --- | ---: | ---: | ---: | ---: |
| 2026-08-21 | Development | 78 | 59 | 21 | 38 |
| 2026-08-22 | Development | 68 | 46 | 28 | 18 |
| 2026-08-23 | Development | 79 | 71 | 23 | 48 |
| 2026-08-24 | Confirmation | 40 | 33 | 12 | 21 |

Parents start at opening +60 seconds. The independent recording bound is the
opening +90-second extraction boundary. A five-second watchdog/staleness rule
invalidates unknown quiet periods until a new full snapshot. Capture time is the
modeled receive timeline; actual exchange time remains unknown. No recording
endpoint is inferred from future payloads.

Five policies (immediate, TWAP, liquidity, retained legacy horizon and joint
horizon), four execution scenarios, buy/sell, 25/100 lots, 5/30-second deadlines
and two compute modes give 84,800 configured attempts. One lot is 0.01 share;
one tick is $0.001/share; one money unit is $0.00001. The common benchmark is the
recorded parent-start midpoint, held outside policy observations. Every policy
uses the same small-order cap and unfinished penalty of 10 ticks per lot.

All 56 invalid-prefix windows retain their reasons: 17,920 trial exclusions.
A further 160 shared cap exclusions cover 32 matched parent/scenario groups.
Together, 66,720 executions +18,080 exclusions account for every attempt.
There is no policy-dependent filtering or outcome downsampling. The completed
traces contain 280,275 fills and 303,351 ledger transitions, each independently
reconciled with zero SQL violations.

## What holds and what remains unresolved

Each cell fixes region, quote group, policy pair, side, size and deadline.
It compares the same intersection of windows across all four execution scenarios
and both compute modes. A stable cell requires consistent signed differences
and intervals excluding zero in every world. Any unresolved interval keeps the
cell unresolved. All-group and stress/ordinary subgroup cells overlap and must
not be counted as independent evidence.

| Confirmation quote group | Stable | Unresolved | Supported reversal |
| --- | ---: | ---: | ---: |
| All windows | 12 | 68 | 0 |
| Ordinary | 0 | 80 | 0 |
| Stress proxy | 18 | 62 | 0 |

These are conditional window-bootstrap results with 1,000 registered resamples,
not independent-day confidence intervals or multiplicity-adjusted guarantees.
There is only one confirmation day. Mean signs change in some unresolved cells;
that is not evidence of a supported reversal. No dramatic reversal was forced.

## Completion changes the interpretation

Each policy/compute mode has 1,056 confirmation trials requesting 66,000 lots in
total across repeated scenarios, sides, sizes and deadlines. Totals are modeled
counterfactual repetitions, not separate realized market executions. Mean cost
below is the unweighted mean of per-parent signed cost/lot, including the fixed
unfinished penalty. It must be read together with completion and tail costs.

| Policy | Filled, zero compute | Filled, measured compute | Unfinished, measured | Mean cost ticks/lot, measured |
| --- | ---: | ---: | ---: | ---: |
| immediate | 65,000 | 63,000 | 3,000 | 53.772 |
| twap | 59,142 | 58,730 | 7,270 | 44.394 |
| liquidity | 59,568 | 59,280 | 6,720 | 45.933 |
| legacy_horizon | 59,125 | 58,875 | 7,125 | 34.477 |
| horizon | 20,898 | 19,862 | 46,138 | 6.917 |

The joint horizon filled only 19,862/66,000 lots in measured mode, leaving 46,138
unfinished. Immediate filled 63,000/66,000. The planner can prefer noncompletion
under the registered 10-tick penalty and wide quotes. Its stable lower-cost
cells do not establish better execution service. Raising that penalty or adding
a completion constraint would be a new hypothesis and registration, not a
post-confirmation repair of these results. No parameters were changed after
outcome evaluation.

## Policy overhead matters

Before outcomes, 5,000 cold constructor-plus-first-decision measurements per
policy used only the first 32 eligible development prefixes. Frozen p99 values
rounded up to milliseconds give 1 ms for immediate/TWAP/liquidity, 3 ms for
legacy horizon and 6 ms for joint horizon. The shared decision budget is 1 second;
none exceeded it. No empirical over-budget fallback result is claimed.

Compute duration shifts arrival time and can change an exact timestamp tie,
staleness boundary or last feasible action. Joint-horizon confirmation fills
fall from 20,898 to 19,862 when measured compute is included. Its mean per-parent
cost rises from 5.075 to 6.917 ticks/lot. This is fixed-duration desktop sensitivity,
not a calibrated distribution of live exchange latency. [Systems evidence](PERFORMANCE.md).

## Reproduce and inspect

[Protocol](PROSPECTIVE_PLAN.json), [frozen registration](STUDY_REGISTRATION.json),
[window manifest](prospective-window-manifest.json), [calibration](COMPUTE_CALIBRATION.json),
[aggregate results](study-summary.json) and
[independent audit](../evidence/completion-study-review.json) are retained.
The complete study asset contains `study/report.html`, `results.json`, every
executed trace and the exact prepared sessions. Open the HTML locally and filter
confirmation, policy pair, side or quote group. Complete outcome and tail-cost
summaries remain available, not only selected comparisons.

```sh
python -m tools.prepare_prospective --source data/15m-archive/updown_15m.parquet \
  --known-ids data/15m-archive/prior_known_ids.json --plan docs/PROSPECTIVE_PLAN.json \
  --output /tmp/queuecraft-sessions
queuecraft study /tmp/queuecraft-sessions --plan docs/PROSPECTIVE_PLAN.json \
  --raw-archive data/15m-archive/updown_15m.parquet \
  --calibration docs/COMPUTE_CALIBRATION.json --out /tmp/replayed-study
```

The saved calibration validates portable source, plan, archive, prefix and
session identities and avoids wall-clock remeasurement. Synthetic frozen-study
replay and genuine installed-order wall-speed controls pass. The independent
artifact checker streams all traces and reexecutes the analytical SQL; the full
study was not redundantly recalibrated after confirmation.

The [five-minute study](history/FIVE_MINUTE_STUDY.md), empty ordinary category,
endpoint-defect witness and superseded source remain historical attempts.
They are not silently relabeled as this registered experiment. No queue-position,
exchange-continuity, market-impact or broad market-generalization claim is made.
