# Independent final study review

Scope: read-only review of production `evidence/prospective-study-v1`, including
raw/normalized identity, saved development-only calibration, trace accounting,
the complete 84,800-attempt registry, per-window SQL, summaries and conditional
paired-window uncertainty. No strategy execution, tuning or fresh calibration.

Entry point: `evidence/completion-study-review.py --sql`. Run after a complete
`results.json` exists and the concurrent C++ benchmark has finished. It writes
only `evidence/completion-study-review.json`; retain its terminal log separately
under this same prefix. Package sources remain frozen throughout production.

Prepared source review confirmed five-second watchdog consistency; independent
recording metadata, evaluation-private benchmark and a fixed one-second budget.
Twelve tiny runner controls passed in the earlier readiness review. At that
preparation stage, the final artifact pass was pending; its completed result is
recorded separately below.

Saved calibration, without remeasurement: 5,000 samples per policy, first 32
eligible chronological development prefixes, all opening on 2026-08-21. Durations
are immediate/TWAP/liquidity 1 ms, legacy horizon 3 ms, new horizon 6 ms. All are
below the one-second budget, so production cannot establish an over-budget
fallback outcome. Controlled tests cover that behavior. Durations are a fixed
desktop-work sensitivity, not a measured exchange/network latency distribution.

Mandatory interpretation limits: operational quote/depth proxies are not
externally established crisis labels; snapshot agreement cannot identify full
exchange-message continuity or individual liquidity identity; one confirmation
opening day does not supply independent-day uncertainty. Source/hash checks and
retained registrations document reproducibility, not proof that no unseen prior
trial ever occurred. Preserve unresolved results and all exclusions.

## Completed artifact review

Full `--sql` checker exited 0. See `completion-study-review.json` and `.log`.
It reconstructed 84,800 configurations as 66,720 executions plus 18,080
exclusions, including 17,920 configurations from 56 prepared-invalid windows
and 160 shared 100-lot cap exclusions for one development BNB window. All 209
eligible windows still have executed trials. It checked 280,275 fills and
303,351 ledger transitions, reproduced every saved SQL report across all 209
window batches, and exactly recomputed all 480 paired/common-window uncertainty
and status cells from trace-derived rows. Source/manifest/calibration/native
identities and the 520,745,135-byte final artifact footprint also passed.

Confirmation classifications: all-condition 12 stable / 68 unresolved;
ordinary proxy 0 stable / 80 unresolved; stress proxy 18 stable / 62 unresolved.
No established reversal. These overlapping strata must not be added together
as independent evidence, and all interval statements remain conditional on the
correlated windows from the single confirmation opening day.

The new horizon's low penalized cost accompanies substantial noncompletion.
Balanced confirmation means, zero work / measured work respectively: 5.0752 /
6.9170 ticks per lot and 31.7869% / 30.2746% completion. Immediate execution has
52.7744 / 53.7719 cost and 98.4848% / 95.4545% completion. These descriptive
cross-policy numbers do not establish execution superiority. The common fixed
10-tick unfinished-lot penalty permits avoiding expensive fills. Measured work
changes horizon completion by about -1.51 percentage points on this balanced
grid; it changes exact-timestamp tie/deadline behavior, not the historical market.
No production decision missed the one-second budget. New horizon had 177 /
589 orders arriving after intent deadline in zero / measured modes; those fills
were forbidden and residual penalties retained. Late-order counts differ from
computation-budget misses and must not be conflated.

Artifact SHA256:
- results: `0bf56165ba7955980860daaf41e4b3089d212e5caf25be0ba488c718275b60b5`
- traces: `d293b2ebdc23a1878f7ec8cae2eab169df28cd06f6ac8af69346588fef91b21a`
- calibration: `0c0c1608d66c7388971a880e940c936337d59d1f18373f86ed091f5486e2fba7`
- registration: `bf605366006cf3c092757c527b60aa0f04ee954af3f430e01f72932e02de2b2b`
- checker: `994fb42f858c11d2fbf9929e2bbb82594a6b4425c37c8757ce42b292d7949f84`
- review JSON: `4ef0d1b15a49c0ffd2c19769b80e846b3133d660be0bfe8f452404e686a97e41`

No package source changes, strategy runs, timing remeasurement, tuning,
commits or public operations occurred in this artifact review.
