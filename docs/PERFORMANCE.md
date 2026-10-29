# Systems measurements

The completion revision separately measures parsing, book updates, persistence,
replay, execution accounting, policy computation and the durable Python
pipeline. These are shared-desktop measurements on arm64 macOS 27.2,
Python 3.14.7 and Apple Clang 21.0.0. Native and pipeline benchmarks ran
sequentially alongside one study worker. They do not measure exchange/network
latency or establish real-time deployment capacity.

Frozen package sources, the native source manifest and the loaded extension
were checked before and after measurement. No runtime source changed. Builds
and disposable journals used a fresh temporary workspace; historical evidence
was preserved. Exact commands, workload identities, hashes and terminal process
results are in
[completion-v3-benchmark-summary.json](../evidence/completion-v3-benchmark-summary.json).
A separate current C++ consumer compiled and ran using only installed headers
and the static library outside the source tree:
[completion-v3-cpp-installed.json](../evidence/completion-v3-cpp-installed.json).

## Policy computation and modeled deadlines

Current policy measurements reuse the production protocol's frozen,
development-only calibration. Each policy has 5,000 timed samples cycling the
first 32 eligible development prefixes, with one warmup per prefix. Each timed
sample constructs a fresh policy and computes its first decision. This means
fresh-object computation, not a cold interpreter or flushed processor caches.
No confirmation data, fills or outcomes were used.

| Policy | Samples | Median | 95th percentile | 99th percentile | Declared compute duration |
| --- | ---: | ---: | ---: | ---: | ---: |
| Immediate | 5,000 | 0.333 µs | 0.375 µs | 0.417 µs | 1 ms |
| TWAP | 5,000 | 0.667 µs | 0.750 µs | 0.833 µs | 1 ms |
| Liquidity-aware | 5,000 | 1.458 µs | 1.584 µs | 4.750 µs | 1 ms |
| Legacy horizon | 5,000 | 0.964 ms | 1.811 ms | 2.661 ms | 3 ms |
| Joint receding horizon | 5,000 | 3.722 ms | 4.848 ms | 5.286 ms | 6 ms |

Nearest-rank percentiles were independently recomputed from every saved raw
nanosecond sample. The protocol rounds each policy's 99th percentile upward
to an integer millisecond, explaining the 1 ms duration for inexpensive
baselines. The shared decision budget remains 1 second; exceeding it invokes
the declared no-op fallback. The study compares zero-duration and measured
per-policy-duration modes. These are deterministic compute-cost assumptions,
not calibrated latency guarantees. Subsequent benchmark contention cannot
change the already frozen durations or a fixed event simulation.

Raw samples, planning configuration, prefix identities and source identity are
retained in
[completion-v3-policy-performance.json](../evidence/completion-v3-policy-performance.json).
The original calibration SHA-256 is
0c0c1608d66c7388971a880e940c936337d59d1f18373f86ed091f5486e2fba7,
matching the study registration. At 5,000 samples the empirical 99th percentile
leaves 50 upper-tail observations. No 99.9th-percentile inference is made.
First-decision costs do not represent every later policy history or order state.

## Native stages and allocations

The native benchmark uses the first development recording named in that fixed
calibration, xrp-updown-15m-1787271300.csv, SHA-256
c81e4f1413f777dafbf69cc7f21efb24fe607a82db2182b7f774b574cd151b1e.
Selection used chronological registration, not policy results. Its first
snapshot has 47 levels and is 1,841 normalized CSV bytes. The replay workload
contains the first ten recorded transactions: six snapshots and four explicit
gap invalidations, totaling 10,820 CSV bytes. It is not ten full snapshots.

| Stage | Samples | Median | 99th percentile | 99.9th percentile | Operations/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Parse one genuine snapshot | 10,000 | 7.584 µs | 14.000 µs | 16.042 µs | 127,807 |
| Three-level controlled update burst | 20,000 | 0.125 µs | 0.166 µs | 0.209 µs | 7,405,120 |
| Append/write | 10,000 | 2.833 µs | 12.916 µs | 18.125 µs | 234,975 |
| Append plus fsync | 10,000 | 29.875 µs | 1.556 ms | 6.540 ms | 14,318 |
| Ten-transaction complete-trace replay | 10,000 | 0.168 ms | 0.251 ms | 0.390 ms | 6,022 |
| Ten-transaction parse/book/IOC/trace | 10,000 | 0.189 ms | 0.589 ms | 2.662 ms | 4,681 |

An operation in either last row processes ten transactions. Their event rates
are approximately 60,218 and 46,806 transactions/s. These are different timed
operations: replay accumulates one complete trace string; parse/book/IOC/trace
attempts a one-lot IOC after every transaction and discards each intermediate
trace after accounting for its size. A gap blocks fills.

Global C++ new/new[] instrumentation counts requested allocations inside each
timed operation, with instrumentation overhead included. Counts below are per
operation; raw cumulative totals remain in the JSON.

| Stage | Allocation calls/operation | Requested bytes/operation |
| --- | ---: | ---: |
| Snapshot parser | 55 | 5,360 |
| Controlled update | 4 | 192 |
| Append/write | 0 | 0 |
| Append plus fsync | 0 | 0 |
| Ten-transaction replay | 971 | 147,800 |
| Ten-transaction parse/book/IOC/trace | 979 | 110,216 |

Zero counted allocations for persistence does not mean zero operating-system
or filesystem resource use. These counters do not measure every C-library or
kernel allocation. Requested bytes are cumulative allocation traffic, not live
memory. Whole-process peak resident memory was **9,551,872 bytes (9.11 MiB)**
across input loading and all stages, not a separate peak for each stage.

The 20,000-update burst changes one absolute ask level in a three-level book.
It measures small-book transaction overhead, not deep-book capacity or a
captured exchange burst. Transaction copies remain; allocation-free updates
are not claimed. Appends use unbuffered write; the fsync stage appends and calls
fsync for every sample. It makes no physical power-loss or macOS F_FULLFSYNC
guarantee. At 10,000 samples, the empirical 99.9th percentile has ten upper-tail
observations, so this extreme tail remains sparsely sampled.

Complete stage evidence, including 95th percentiles, throughput, source/input
hashes and allocation totals, is in
[completion-v3-cpp-benchmark.json](../evidence/completion-v3-cpp-benchmark.json).

## Durable pipeline

The integrated benchmark repeats this full path 1,000 times:

1. Append two genuine, label-free early BTC archive snapshot projections to a
   new raw journal, then fsync it.
2. Restore and check record lengths/CRC, normalize fixed-point quantities and
   insert the declared gap invalidation.
3. Run the native parser/book, observation scheduler, TWAP, hypothetical IOC
   fills and ledger with explicit recorder coverage.
4. Export the result as JSON and fsync it.

Each operation processes two projected messages totaling 2,439 bytes. Network
acquisition and the separate analytical SQL audit are outside this timing.
These are archived snapshot projections, not original exchange wire messages.

| Samples | Median | 95th percentile | 99th percentile | Operations/s | Peak process resident memory |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 2.272 ms | 2.576 ms | 3.015 ms | 442.09 | 83,361,792 bytes (79.50 MiB) |

Resident memory includes the process's archive-query setup and all repetitions.
All 1,000 operations produced the same result SHA-256:
8363707d33a1e2dd108e8ee4723f95a50999b0035aa9f77a803585d536aa1434.
The empirical 99th percentile has ten upper-tail observations; no 99.9th
percentile is reported. This is a small integration workload, not burst capacity
evidence. See
[completion-v3-e2e-benchmark.json](../evidence/completion-v3-e2e-benchmark.json).

## Comparisons and limits

Historical measurements remain under evidence/ as python-benchmark-v1.json,
cpp-benchmark-v0.1.0-v2.json and e2e-benchmark-v2.json. The earlier invalidated
first native measurement also remains explicitly marked as superseded.

The historical Python benchmark timed 10,000 warm calls on one repeated
observation and excluded construction. Its old horizon name refers to the
policy now retained as legacy_horizon; the new joint horizon performs a
different common-plan optimization. Those timings cannot establish a current
policy speedup or regression.

The historical native benchmark used a different BTC recording, a 3,783-byte
first snapshot and a 34,725-byte replay prefix. The current XRP/gap workload is
smaller. Shared scheduling also differs. Lower current times therefore do not
establish an engine optimization. The identical three-level burst still
records four allocations and 192 requested bytes per update, matching the
retained baseline. Book/accounting hotpaths were verified byte-identical in
the recording-boundary revision.

The prior integrated benchmark used the same two-message/2,439-byte raw
workload and recorded median 5.660 ms, 99th percentile 13.563 ms and
161.29 operations/s. Current source records 2.272 ms, 3.015 ms and
442.09 operations/s. This is a descriptive comparison of separate shared-host
runs, not a controlled speedup claim. Source and coverage handling changed;
cross-version result-byte equality is not asserted. Within-run determinism is
verified.

No CPU frequency, core isolation, maximum-load capacity or exchange latency
guarantee is inferred. No HftBacktest performance comparison was attempted
without matched inputs and execution semantics.
