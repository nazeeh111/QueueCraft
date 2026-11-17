# QueueCraft

**Follow an order from the book it observes to the account it changes.**

An embeddable C++20 execution-research engine with exact tick/lot accounting,
a typed Python strategy SDK and replayable CLI reports. Delayed observations,
hypothetical arrivals and acknowledgements stay separate. Research software
**0.1.1.dev0**; no brokerage route or live orders.

<picture>
  <source media="(max-width: 600px)" srcset="docs/presentation/order-timing-mobile.svg">
  <img src="docs/presentation/order-timing.svg" alt="Synthetic seven-lot sell: at zero modeled latency, four lots fill at 100 ticks and three at 99; at 55 ms, a 50 ms depth update happens first, yielding two at 100 and five at 99. After two per-fill fees, cash is 695 versus 693 tick×lot units. Both recorded exports replay exactly.">
</picture>

Same synthetic input, same seven-lot sell, one changed assumption. A recorded
update at **50 ms** reduces the 100-tick bid from four lots to two. Arrival at
**55 ms** therefore reaches different depth than arrival at zero. Each case
fills all seven lots; net cash differs by two tick×lot units. This illustrates
the execution model, not measured network latency or a policy advantage.

[Reproduce and inspect the worked case](docs/presentation/README.md) ·
[Download the complete example](docs/presentation/worked-example.zip) ·
[Public C++ header](include/queuecraft/engine.hpp) · [Python consumer](examples/strategy.py)

## Check the native engine first

A C++20 compiler and `make` are enough for the bundled synthetic core checks;
no Python packages, account or market connection are needed:

```sh
git clone https://github.com/nazeeh111/QueueCraft.git
cd QueueCraft
make test
```

This checks the native book and accounting contracts. It is not a replay of
the registered market-data study or evidence of live execution performance.

## Current-source first run

Requires Python 3.11+ and Clang/GCC with C++20 on macOS/Linux. The `study`
extra supplies pinned DuckDB 1.4.3 for SQL reconciliation. From this checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[study]'
queuecraft --version
queuecraft simulate examples/stream-synthetic.csv --side sell --size 37 \
  --policy immediate --recording-end-ns 7000000000 --deadline 4 \
  --latency-ms 55 --fee-ppm 100 --out synthetic-order
queuecraft verify synthetic-order
```

This tiny synthetic recording has a declared 7-second coverage bound. It is a
local accounting example, not observed trading or a new study. The saved order
includes the original input, configuration, complete result, SQL reconciliation
and HTML report. Choose a new output directory for each simulation; existing
exports are refused.

Open `synthetic-order/report.html` locally. Run `queuecraft verify .` from inside **that export
directory**, or `queuecraft verify synthetic-order` from the checkout. Verification recomputes the complete trace
and SQL accounting and compares saved field types as well as values. JSON key
order and whitespace may differ; integer fields remain integers and boolean
flags remain booleans. A replay mismatch exits 2 without rewriting the export.
Hashes identify input bytes; they do not authenticate an accounting record.

## Published 0.1.0 workflow

These commands use the historical release from its own checkout. Current-source
installation and streaming instructions above use the new development generation.

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/nazeeh111/QueueCraft.git queuecraft-release
cd queuecraft-release
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[study]'
queuecraft validate examples/recorded.csv
queuecraft simulate examples/recorded.csv --size 25 --policy twap \
  --recording-metadata examples/recorded-provenance.json --out first-order
queuecraft verify first-order
```

Open `first-order/report.html`. Change to `--size 50` and a fresh output folder
to compute a new trace. The [saved example](examples/demo/report.html) includes
input, configuration, every decision/order/fill, recorded books and SQL checks.
GitHub displays HTML source; open a local download to interact.

Recording coverage is explicit metadata, independent of the final book message.
A quiet recording can end after its last quote. `--recording-end-ns` or
`--recording-duration-seconds` can provide a known acquisition bound instead.
Do not invent a recording end to extend data availability. Sparse or stale
quotes still obey the declared watchdog and staleness rules.

On Apple Silicon with a universal Python installation, use
`ARCHFLAGS="-arch arm64"` for the install if a second architecture is unavailable.
No trading credentials, model weights or billed service are used.

## Add an installed strategy

```python
from queuecraft import Observation, OrderRequest

class OneLotAtATime:
    def decide(self, observation: Observation) -> OrderRequest:
        return OrderRequest(min(1, observation.remaining))
```

Callbacks receive immutable delayed market prefixes, acknowledged fills and
remaining reservations. Recorder bounds are declared inputs; future payloads
cannot change earlier callbacks, fills or acknowledgements when those bounds
are held fixed. Evaluation-only benchmark prices are not placed in the strategy
observation. Strategies are trusted Python, not a security sandbox.

The separate [consumer](examples/strategy.py) uses only installed public APIs.
It declares the bundled example’s known 31-second extraction bound; for another
recording, replace that declaration with its independently known coverage:

```sh
# From outside the source checkout, after installation:
python /path/to/strategy.py /path/to/recorded.csv 25
```

The C++ [public header](include/queuecraft/engine.hpp) exposes strict parsing,
`Engine::apply` and `Engine::take`. Install a static SDK and compile the separate
[C++ consumer](tests/cpp/consumer.cpp) against installed files only:

```sh
make all
make install PREFIX=/tmp/queuecraft-sdk
c++ -std=c++20 -pthread -I/tmp/queuecraft-sdk/include \
  tests/cpp/consumer.cpp /tmp/queuecraft-sdk/lib/libqueuecraft.a -o /tmp/consumer
/tmp/consumer
```

## Models and evidence

| Part | Implemented contract |
| --- | --- |
| State | Single writer; atomic full snapshots or absolute updates; zero deletes; invalid after a gap until a new snapshot; bounded input |
| Arithmetic | Checked 64-bit ticks/lots, integer tick×lot money, per-fill fee ceiling and rollback on overflow |
| Timing | Exchange, capture, policy observation, hypothetical arrival and acknowledgement remain separate; declared ties and no-op deadline fallback |
| Execution | Marketable IOC sweeps, partial fills, exact signed cash/inventory and consumed liquidity across surviving recorded levels |
| Policies | Immediate, TWAP, a spread-aware baseline, the retained prior horizon heuristic and a joint latency/liquidity horizon policy |
| Verification | Complete independent Python/native traces, substantive DuckDB joins/windows, causal mutations, installed consumers and systems measurements |

TWAP splits an order over time. Receding-horizon planning recomputes a remaining
order plan after each observation. The new planner scores the same future plan
across a fixed latency/liquidity/drift family; it cannot select different future
actions with knowledge of the hidden environment. [Planning method](docs/PLANNING.md).
It remains a finite heuristic, not a calibrated guarantee or proof of advantage.

The small-order regime is declared: the bundled study caps parents at 100 shares
and 1% of initial opposing top-ten depth on either side. Generic imported units
and caps are the caller's responsibility. Historical markets do not react to
hypothetical trades. There are no passive orders, observed queue positions or
maker rebates; taker fees are explicit nonnegative research assumptions.

## Registered prospective study

The new protocol uses licensed 15-minute binary-contract windows across eight
assets and four capture dates. Entire opening UTC days are reserved before
eligibility: August 21–23 development, August 24 confirmation. A prefix-only
quote/depth rule defines operational stress proxies. These are not independently
established financial-crisis labels. Both proxy groups are represented in the
prepared confirmation set.

```sh
python -m tools.prepare_prospective --source data/15m-archive/updown_15m.parquet \
  --known-ids data/15m-archive/prior_known_ids.json --plan docs/PROSPECTIVE_PLAN.json \
  --output /tmp/queuecraft-sessions
queuecraft study /tmp/queuecraft-sessions --plan docs/PROSPECTIVE_PLAN.json \
  --raw-archive data/15m-archive/updown_15m.parquet \
  --calibration docs/COMPUTE_CALIBRATION.json --out /tmp/queuecraft-study
```

The completed run accounts for **84,800 attempts: 66,720 executions and 18,080
retained exclusions**. Independent review recomputed all 209 SQL batches and
480 paired comparison cells. Confirmation has 30 stable and 210 unresolved
stratified cells, with no supported reversal. The horizon policy's lower
penalized cost comes with poor completion: measured mode fills 19,862 of 66,000
requested lots. This does not establish execution superiority.
[Results and interpretation](docs/STUDY.md) · [Aggregate results](docs/study-summary.json) ·
[Complete study archive](https://github.com/nazeeh111/QueueCraft/releases/download/v0.1.0/queuecraft-study-v0.1.0.tar.gz).

Saved calibration reproduces the registered compute durations without new
measurements. Omitting `--calibration` runs a separate desktop timing sensitivity.

The protocol retains all window attempts and exclusions, both sides, sizes and
deadlines, execution assumptions and measured policy-computation sensitivity.
[Protocol](docs/PROSPECTIVE_PLAN.json) · [Data contract](docs/DATA.md).
Window uncertainty is conditional on correlated observations. A single
confirmation day does not establish broad independent-day evidence.

The [first five-minute experiment](docs/history/FIVE_MINUTE_STUDY.md) remains a
prior attempt. Its ordinary class was empty, and a subsequent completion audit
found future-endpoint dependence and incomplete latency planning. Its source,
registrations and negative results are preserved. Current commands reject its
old registration instead of silently rerunning a different policy under its
name. It is not the final prospective study.

## Incremental replay

For the same bundled synthetic input, the command below emits NDJSON (one JSON
record per line). A file produced by `stream` is a transition stream, not the
complete `simulate` export directory used by `verify`.

`queuecraft stream` reads the CSV once, keeps one source event ahead, and emits
NDJSON transitions as they occur. Supply the recorder's coverage and the order's
start explicitly; these never come from a later source event.

```sh
queuecraft stream examples/stream-synthetic.csv --start-ns 0 --deadline-ns 5000000000 \
  --recording-end-ns 12000000000 --size 1 --out replay.ndjson
```

The example uses synthetic data. Use timestamps matching your recording. `--out`
publishes the fully written record stream exclusively; an existing file is
preserved. The file can still end with `incomplete`, so inspect the terminal
record and exit status. Without `--out`, stdout cannot retract prior records.
The last record is `complete` or `incomplete`; an incomplete run exits 2 and
has no final result. Earlier transitions are provisional. Input failure, policy
failure and a pending-event budget stop all produce explicit incomplete status.
Only source exhaustion supplies the final input digest. This command does not
create the full SQL-reconciled study/export bundle used by `simulate`.

The Python API supports incremental consumers:

```python
from queuecraft import CSVEvents, Intent, Scenario, stream
from queuecraft.policies import Immediate

with stream(CSVEvents("recording.csv"), Intent("buy", 1, 0, 5_000_000_000),
            Immediate(), Scenario(), recording_end_ns=12_000_000_000) as replay:
    for transition in replay:
        process(transition)  # discard or persist each detached record
    if replay.status == "complete":
        print(replay.result.filled)
```

Collection is off by default: result lists are empty and scalar totals remain
exact. `collect=True` / `--collect` retains all decisions, orders, fills and
ledger rows; `trace_books=True` / `--trace-books` includes recorded book traces.
The existing `run()` remains a full collector. Neither interface resumes a
partially consumed native simulation. Close an iterator you stop early.

Memory depends on book depth, the active observation-delay/timestamp-tie window,
active orders, policy state and any records retained by the caller. The default
100,000 pending-event budget refuses overfull windows rather than changing event
order; adjust `max_pending_events` / `--max-pending-events` explicitly. CSV reads
have a 4 KiB row limit and the native 20,000-row event limit, while total streaming
input can exceed the batch parser's 64 MiB bound. The unchanged native validator
checks every raw event before use. The scheduler consumes one thread only.

## Develop and verify

```sh
python -m pip install -e '.[study]'
make test
make sanitize
make tsan
python -m unittest discover -s tests -v
python -m tools.differential examples/recorded.csv --out /tmp/differential.json
```

The native book/accounting hot path preserves the independently checked
baseline; native order execution now also requires recording bounds. Scheduler tests also append later events while keeping recording
metadata fixed, checking every earlier callback/fill/ack. DuckDB independently
validates every ledger transition, run isolation, exact money units, recorder
bounds, missing values and references. Unsupported sanitizer/fuzzer capabilities
are disclosed separately from passing checks.

`RawCapture` journals original bytes supplied by an embedding read-only collector.
Truncation or CRC failure requires a fresh snapshot/session. The bundled archives
are recorded snapshots, not exchange-sequenced wire messages. Actual exchange
time, intersnapshot order and individual liquidity identity remain unidentified.
Restoring an exported order means deterministic replay of its full configuration;
there is no durable partial native checkpoint or crash-atomic exchange service.

[Architecture](docs/ARCHITECTURE.md) · [Exact contract](docs/CONTRACT.md) ·
[Validation](docs/VALIDATION.md) · [Performance](docs/PERFORMANCE.md) ·
[Differences from existing projects](docs/DISTINCTION.md) · [Data licenses](data/README.md) ·
[Owner walkthrough](docs/WALKTHROUGH.md).

## Architecture and versioned provenance

![Execution architecture](docs/architecture.svg)

[Historical0.1.0 release and checksums](https://github.com/nazeeh111/QueueCraft/releases/tag/v0.1.0) ·
[Public verification evidence](https://github.com/nazeeh111/QueueCraft/releases/download/v0.1.0/delivery-evidence.json).
The current-source workflow above uses the development generation.
