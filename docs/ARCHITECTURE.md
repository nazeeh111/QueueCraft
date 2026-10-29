# Architecture and units

Editable source: [architecture.mmd](architecture.mmd), rendered editable SVG:
[architecture.svg](architecture.svg). Each node names an actual module.

The archive adapter projects nine permitted columns, reconstructs a full
snapshot at every valid observation, and emits G for malformed/one-sided/crossed
observations or capture gaps over five seconds. There are no fabricated update
messages between archive snapshots. Such intersnapshot events are unidentified.

Native `Engine` serializes each transaction on its owning thread. A candidate
book/consumption/ledger state is checked before commit, preserving state on
overflow or malformed input. Current std::map copies are deliberately simple;
allocation and memory measurements accompany throughput. The native extension
uses capsules to maintain ownership; calls from another thread fail.

The scheduler keeps independent actual and observed native books. Market events
affect the actual book at recorded capture time; delayed copies affect the policy
view later. Decisions reserve remaining parent intent until acknowledgement.
Orders and cancellation requests arrive after their declared delays. Canceled
pending IOC orders release reservations on acknowledgement; a replacement can
then consume remaining intent. Arrivals after deadline or recording end expire.
Recorded-first versus arrival-first ties are declared scenario choices.

The reference is independently implemented in Python with arbitrary-size integer
intermediates and explicit64-bit bounds. It checks full state and ledger traces.
DuckDB separately checks integer money products, per-fill fee ceilings, causal
timestamp joins, fill/order conservation, complete ledger coverage and cumulative
window sums. It is not a pandas reporting wrapper.

For the real archive:1tick=$0.001/share,1lot=0.01share,1money=$0.00001.
For generic imported CSV, the caller declares units. `shortfall2` is exactly
twice money units, preserving half-tick midpoint benchmarks without floats.
Cash and inventory begin at zero as signed account deltas, not a funded broker
account. Negative cash means purchase expenditure. No financing model exists.

Native capture retains original bytes, receive time, length and CRC in a fresh
append-only file. Imported Parquet is retained byte-for-byte with SHA256. CRC
detects corruption; it is not adversarial authentication. Hashes attest local
reproducibility, not independent timing or absence of prior trials.

Recording end is explicit terminal metadata supplied separately from event
payloads. The scheduler never uses the final event's timestamp to decide whether
to expose earlier callbacks or fill/acknowledgement state. This repairs the
prior endpoint dependency, including append/truncation controls. A common
evaluation benchmark is held outside the strategy's Observation and Intent.

The current horizon policy enumerates one common cumulative action plan across
a fixed joint family of latency, liquidity and drift assumptions. Its next
action minimizes worst-case modeled cost, then it recomputes from the next
available prefix. It does not learn the execution scenario or choose different
future actions for each hidden environment. Development-only compute timings
are frozen as explicit duration inputs before outcome evaluation.
