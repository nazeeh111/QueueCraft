# Executed study: rankings remain unresolved on confirmation

All 5,632 registered policy/scenario/order combinations executed, with no
exclusions. They cover 44 genuine short market windows, both order sides,
0.25/1 share parents and 5/30 second deadlines. Independent review reran the
SQL on 32,914 fills and 33,939 ledger transitions, and exactly recomputed every
paired mean, seeded 1,000-window bootstrap interval and stability status.

**All 48 confirmation policy-pair comparisons are unresolved.** Twenty-six change mean
sign across the scenarios, but their uncertainty prevents calling those
established reversals. Development has 15 stable and 33 unresolved comparisons.
The receding-horizon heuristic does not establish an advantage over immediate
execution and carries substantial measured computation overhead.

Balanced confirmation grid, equally weighting each scenario/side/size/deadline
cell across the same 18 windows. These are descriptive summaries, not a selected
winner or a calibrated comparison:

| Policy |Mean signed cost, ticks/lot |Mean completion |
| --- | ---: | ---: |
| Immediate |6.2631 |96.53% |
| TWAP |6.6090 |85.66% |
| Liquidity-aware |6.4435 |89.65% |
| Receding horizon |6.2695 |93.75% |

Costs include the common fixed unfinished-lot penalty and hypothetical fees.
Lower cost can accompany lower completion. One tick is $0.001/share; one lot
is 0.01 share. Negative signed shortfall denotes favorable price movement versus
the initial captured midpoint, not strategy profit. Detailed scenario-level
completion, 95th-percentile costs, fees and unfinished lots are in results.json.

The spread threshold was registered as the development 75th percentile of initial
spreads. It equaled 10 ticks, and all 44 windows satisfy the inclusive threshold.
The ordinary class is empty. This failed coverage test is retained: the study
cannot contrast ordinary and stressed market sessions. Relabeling windows after
examining policy costs would not fix the preregistered experiment.

Only one capture day is available. These short markets are correlated, so
window bootstrap intervals are descriptive and do not supply independent-day,
selection-corrected or general market inference. Snapshot capture times are not
exchange/receive times. Actual exchange sequences and intersnapshot queue
identity are unavailable. The source contains one-sided/crossed observations;
invalidations and gap/resynchronization records remain in normalized input.

Original plan and manifest hashes are in registration.json. Policies, fees,
scenarios, penalty and window split were frozen before evaluation. Superseded
normalization and interrupted correctness/validation runs remain task-local;
none is represented as a successful final study. There was no policy tuning
on confirmation. Original code hashes are retained. Two subsequent changes
are separately disclosed in evidence/study-source-delta.json: a raw-journal
negative-time guard and this report's display of the empty ordinary class.
No policy, book, accounting, data normalization or study calculation changed.

The versioned study archive contains registration, all raw/normalized inputs,
full traces, results, the current portable HTML report, original changed display/
capture sources and attribution. The public source contains the compact raw
archive and the exact normalizer needed to recreate normalized sessions.
