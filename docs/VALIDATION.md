# Executed validation

Current local environment: arm64 Mac, Apple Clang21, Python3.14.7,
DuckDB1.4.3. The evidence JSON files record input/native/source hashes.

| Check | Executed outcome |
| --- | --- |
| Native unit/failure |238 assertions plus12000 deterministic parser mutations pass |
| Address/undefined behavior |238 assertions plus12000 mutations pass with ASAN/UBSAN |
| Thread sanitizer |same cases pass, including wrong-thread owner rejection |
| Python |42 tests pass, including data-label mutation, capture corruption, delayed prefix invariance, wall-clock invariance, ties, cancellation/replacement and deadline fallback |
| Independent reference |21 reference tests, written without inspecting C++ implementation |
| Corrected real-data differential |52 cases,12630 complete books,6200 order attempts,5076 fills,17 failure/atomic controls, every compared field equal |
| Installed C++ consumer |static library and header-only include path from fresh installation; separate consumer passes |
| Genuine changed order |25-lot and50-lot TWAP executions produce distinct traces and account deltas |
| Export replay |25-lot example exact replay; DuckDB checks4transitions/4fills with zero violations |

Full data comparison: `evidence/differential-v2.json`. Native gate details:
`evidence/cpp-gates-v1.json`. Seeded mutation tests include truncation,
duplicates, crossed/corrupt books, tick/integer violations, overflow rollback,
snapshot atomicity, gap/resynchronization, ownership and shutdown.

Independent review found coverage-end fills, absent/orphan ledger acceptance,
policy duration omitted from last feasible decision, and forged canceled-status
exemption. Missing SQL fields and cross-run isolation also received explicit controls. All received substantive regression controls and were fixed before
final study evaluation. SQL joins/windows are tested by corrupting nonclosing
ledger rows, dropping every transition, adding duplicate fills, changing units
and moving capture timestamps after arrival.

Capability limits: Apple LeakSanitizer is unavailable, so ASAN leak detection
was disabled after retaining the failure; this is not a leak-check pass. Xcode
lacks the optional libFuzzer runtime; that linker failure is retained. The12000
mutation cases executed, but no coverage-guided fuzzer claim is made.

The first normalization incorrectly assumed0.01price ticks. Exact archive
inspection found valid0.001ticks; rejectedv1 is retained task-locally andv2 was
frozen before policy evaluation. Provisional studyv1 failed after concurrent
review changes to its SQL schema;v2 was interrupted after another validation
repair. Neither is presented as a completed study.

Raw capture restore means validating/replaying exact journal bytes; exported
order restore means complete deterministic replay of input+configuration+policy.
No durable partial native checkpoint or process-crash recovery is claimed.

Remote CI, final independent installation, final study and release readbacks
are recorded in the delivery evidence once executed; this file does not turn
unexecuted checks into passes.

Final study:5632/5632 combinations executed,32914fills,33939ledger transitions.
Independent artifact review reexecuted all44SQL batches and recomputed every
paired statistic/status. Zero SQL violations; all48confirmation comparisons
unresolved. Ordinary-category coverage is absent, as detailed in STUDY.md.

Final standalone CLI check also passes: complete book/fill/ledger agreement
against the independent model, existing output preservation and pre-output
truncation/64MiB rejection (`evidence/cpp-cli-final.json`). The installed wheel
runs outside the source tree, computes25/50lot changed inputs and verifies both
exactly (`evidence/installed-consumer-v2.json`). `docs/demo.cast` is a short
scripted recording of actual executions, without simulated typing or outcomes.
