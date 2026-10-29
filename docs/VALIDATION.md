# Executed validation

Current completion revision: arm64 Mac, Apple Clang 21, Python 3.14.7,
DuckDB 1.4.3. Evidence records input, source and native-binary hashes. The prior
candidate is preserved in Git and [historical validation](history/CANDIDATE_VALIDATION.md).

| Check | Executed result |
| --- | --- |
| C++ unit/failure | 256 assertions and 12,000 deterministic parser mutations pass |
| Address/undefined behavior | Same cases pass under ASAN/UBSAN |
| Thread sanitizer | Same cases pass, including single-writer owner rejection |
| Python | 76 tests pass before the production source freeze |
| Full independent differential | 274 cases, 13,993 complete books, 8,290 order attempts and 6,839 fills agree; 17 failure controls pass |
| Native order boundary | 360 complete results agree; 16 required-boundary/type/error controls pass |
| Standalone C++ CLI | Full book/fill/ledger agreement, required recording bounds, quiet-prefix invariance, late-arrival expiry and bounded input checks pass |
| Joint planner | Eight small-grid controls include shared-plan worst-case evaluation and latency/liquidity action changes |
| Prospective runner | 12 small synthetic controls cover source/calibration identity, no-clock frozen replay, matched exclusions, bounded reads and artifact accounting |
| Installed C++ consumer | Fresh current static library and public header; separate consumer compiles and runs using installed paths only |
| Installed Python consumer | Fresh rebuilt arm64 wheel; external public example and CLI 25/50-lot executions; exact export replay and zero SQL violations |
| Real-data replay speed | Artificial 20 ms callback delay plus forbidden wall-clock counters preserves every decision, order, fill, ledger entry and book in the fixed simulation |
| Current scripted demo | Installed CLI, changed orders, SQL replay and separate strategy execute successfully; saved example bytes match fresh output |

Evidence: `evidence/completion-cpp-boundary-gates-v1.json`,
`completion-native-differential-v2.json`, `completion-native-boundary-controls-v2.json`
and `completion-cpp-cli-v1.json`. The 76-test terminal log is retained task-locally
as `evidence/completion-suite-final-before-study.log`.

The old scheduler inferred recording coverage from future payloads. An executed
baseline witness reproduced changed earlier callbacks after appending a later
message (`evidence/endpoint-baseline-failure.json`). The repaired Python, native
and C++ entry points require independent recorder-end metadata. Regression controls
compare earlier callbacks, fills, ledger and acknowledgements with fixed bounds;
changing evaluation-only benchmarks cannot reveal information to a strategy.

DuckDB checks each transition through tested joins and windows: missing/orphan or
duplicate records, exact money/fee units, references, run isolation, causal
arrival/capture timestamps, recorder/deadline bounds and cumulative conservation.
Corrupting nonclosing rows or dropping all transitions must produce violations.
Full book traces are compared with the separately implemented integer Python model.

Apple LeakSanitizer is unsupported, so ASAN leak detection was disabled after
retaining its failure. This is not a leak-check pass. Xcode lacks the optional
libFuzzer runtime; that linker failure remains retained. Seeded mutation cases
executed in all three supported builds; no coverage-guided fuzzing claim is made.

The original five-minute study is historical. The distinct registered 15-minute
study completed 66,720 simulations: 84,800 attempts minus 18,080 retained
exclusions. Independent review reexecuted all 209 SQL batches, checked 280,275
fills and 303,351 ledger transitions, and recomputed all 480 paired/common-window
uncertainty/status cells. Confirmation has 30 stable and 210 unresolved
stratified cells, no supported reversals. Horizon's low cost accompanies poor
completion; [full interpretation](STUDY.md) retains that negative result.
Evidence: `evidence/completion-study-review.json` and its notes/script.

The installed consumer is recorded in `evidence/completion-installed-consumer-v3.json`
and genuine scripted demo in `evidence/completion-demo-v3.json`. Initial wheel
platform-label and licensing-file drift attempts were retained before the fresh
final wheel passed. Current performance evidence is indexed in
`evidence/completion-v3-benchmark-summary.json`. Current reports were visually
inspected and study filters exercised. Public CI, public clone, downloads and
release checks remain pending. No public repository or release is verified.

Raw-capture restore validates and replays exact journal bytes. Exported-order
restore replays the complete input/configuration/policy. No durable partial native
checkpoint or process-crash recovery is claimed. Unknown exchange times, hidden
intersnapshot events and individual liquidity identities remain unobserved.
