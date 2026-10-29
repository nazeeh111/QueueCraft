# Systems measurements

This is desktop runtime under shared load, not colocated exchange latency.
The benchmark source retains allocations and transaction-copy costs. No
HftBacktest speed comparison was attempted with unmatched semantics.

Python public API measurements (`evidence/python-benchmark-v1.json`):

| Policy | Samples | Median decision |99th percentile |99.9th percentile |
| --- | ---: | ---: | ---: | ---: |
| Immediate |10000 |0.50µs |0.79µs |3.54ms |
| TWAP |10000 |1.08µs |8.58µs |2.28ms |
| Liquidity-aware |10000 |2.96µs |0.28ms |33.25ms |
| Receding horizon |10000 |4.85ms |236.91ms |495.05ms |

The large tail and mean/median differences reflect real contended desktop
measurements. They are not hidden. The four-stage receding-horizon policy is
substantially more expensive. A200-sample Python end-to-end TWAP run measured
median3.12ms and99th percentile40.35ms. Its sample count does not support99.9th
percentile inference. Peak Python-process RSS was24018944bytes on macOS.

Registered study scenarios use zero modeled policy compute duration, while
these actual costs are measured separately. `policy_duration_ns` and
`decision_budget_ns` allow deterministic compute-delay scenarios; exceeding the
budget invokes a declared no-op fallback. No real-time deployment feasibility
or automatic wall-clock calibration is claimed. Event replay speed cannot
change a fixed simulation.

C++ measurements separately cover strict parsing, small-book updates, complete
trace replay, IOC ledger work, raw append/write, append/fsync and end-to-end
processing. Each stage records sample counts, throughput, tail latency, counted
allocations, observed bursts, source/input hashes and process peak RSS. See
current completed `cpp-benchmark-v2` evidence; superseded first measurements
are retained and explicitly marked, not silently overwritten.

Final C++ benchmark (`evidence/cpp-benchmark-v0.1.0-v2.json`), with source hashes
verified unchanged at completion:

| Stage | Samples | Median |99th percentile |
| --- | ---: | ---: | ---: |
| Parse genuine snapshot |10000 |26.13µs |2.07ms |
| Three-level controlled update burst |20000 |0.208µs |0.292µs |
| Append/write |10000 |4.96µs |35.42µs |
| Append plus fsync |10000 |52.25µs |484.75µs |
| Ten-event genuine full-trace replay |10000 |2.80ms |215.73ms |
| Ten-event parse/book/IOC/trace |10000 |1.99ms |278.17ms |

Peak C++ process RSS was9551872bytes. Raw JSON includes99.9th percentiles,
allocation counts and throughput. Allocation counts are cumulative, not live
memory. The small-book burst is not a deep-book capacity benchmark. Shared-host
scheduling makes tails large and comparisons between separate stages noisy.
No optimization or low-latency deployment claim is made from these results.

The integrated snapshot workload also measures1000runs from genuine label-free
JSON archive projections through append-only journal/fsync, CRC restoration,
fixed-point normalization, native parser, strategy/IOC/ledger and durable JSON
export. Current-source results are in `evidence/e2e-benchmark-v2.json`. This
excludes network acquisition and the separate analytical SQL audit; it does
include policy and persistence overhead. It is a bounded integration workload,
not an exchange wire-feed or high-frequency execution claim.

Current integrated run:1000samples, median5.66ms,95thpercentile10.03ms,
99thpercentile13.56ms,161.3operations/s, peak process RSS83984384bytes.
Each operation journals and processes two genuine early-window snapshots;
it is deliberately a small integration workload, not burst capacity evidence.
The result hash is identical to the retained prior run.
