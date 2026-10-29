# QueueCraft

**An embeddable C++20 execution-research engine that shows where policy rankings depend on assumptions.**

Exact integer books and accounting, a Python strategy SDK, deterministic replay,
independent book/ledger checks, and a registered scenario-stability study.
Research software 0.1.0. No brokerage connection or live orders.

![QueueCraft execution architecture](docs/architecture.svg)

The genuine example uses licensed Polymarket BTC market-depth snapshots. They
are imperfect one-second observations from one day, not an exchange-sequenced
message archive. The engine additionally implements snapshot/update/delete/gap
transactions, verified on controlled event streams. Unknown exchange time stays
unknown. **No profitability, observed queue-position or broad market claim.**

## Run a fresh order

Requires Python 3.11+ and Clang/GCC with C++20 on macOS/Linux. No runtime package
is needed for the core; the SQL study extra installs pinned DuckDB 1.4.3.

```sh
git clone https://github.com/nazeeh111/QueueCraft.git
cd QueueCraft
git checkout v0.1.0
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[study]'
queuecraft validate examples/recorded.csv
queuecraft simulate examples/recorded.csv --size 25 --policy twap --out first-order
queuecraft verify first-order
```

Open `first-order/report.html`. Change `--size 25` to `--size 50` and choose a fresh output directory to compute another trace.
The checked-in [example](examples/demo/report.html) includes original normalized
input, configuration, every decision/order/fill, full recorded books and SQL
reconciliation. GitHub displays HTML source; open a local download in a browser.

For Apple universal-Python installations that request an unavailable second
architecture, prefix the install with `ARCHFLAGS="-arch arm64"` on Apple Silicon.
No trading account, API key, model weights or separately billed API is used.

## Write a strategy against the public API

```python
from queuecraft import Observation, OrderRequest

class OneLotAtATime:
    def decide(self, observation: Observation) -> OrderRequest:
        return OrderRequest(min(1, observation.remaining))
```

Each callback receives an immutable observation prefix, acknowledged progress
and outstanding reservations. It cannot obtain future events from the API.
Strategies are trusted Python code, not a security sandbox. Run the separate
[installed consumer](examples/strategy.py) outside the source checkout:

```sh
python /path/to/strategy.py /path/to/recorded.csv 25
```

The [C++ header](include/queuecraft/engine.hpp) exposes `Engine::apply`,
`Engine::take`, strict parsing and exact arithmetic. Install the static library
and compile [the C++ consumer](tests/cpp/consumer.cpp) using installed files only:

```sh
make all
make install PREFIX=/tmp/queuecraft-sdk
c++ -std=c++20 -pthread -I/tmp/queuecraft-sdk/include \
  tests/cpp/consumer.cpp /tmp/queuecraft-sdk/lib/libqueuecraft.a -o /tmp/consumer
/tmp/consumer
```

## What is modeled

| Layer | Contract |
| --- | --- |
| Book | Single writer; atomic full snapshots or absolute updates; zero deletes; invalid until snapshot after gaps; bounded input; crossed books rejected |
| Arithmetic | Checked 64-bit ticks/lots; integer tick×lot money; per-fill fee ceiling; overflow rolls back |
| Timing | Exchange, capture/receive, delayed observation, hypothetical arrival and acknowledgement separate; declared ties, deadline fallback and cancel arrivals |
| Execution | Marketable IOC sweeps, partial fills, exact signed cash/inventory; consumption persists across surviving levels in later snapshots |
| Fairness | Same information, parent size, cap and unfinished-order penalty for every policy in a scenario |
| Policies | Immediate, TWAP, spread/liquidity-aware baseline, finite receding-horizon minimax planning heuristic |
| Evidence | Complete native/Python differential traces, per-transition DuckDB joins/windows, causal mutation tests, installed consumers and measured systems costs |

TWAP means splitting an order across decision times. A receding-horizon policy
replans the remaining order after each observation. Its hypothetical forecasts
use prefix depth and midpoint movement across several depth/drift assumptions.
Fractional forecast fees and assumed replenishment are planning approximations;
actual execution always uses exact fees and the consumed-liquidity overlay.
The planning scenarios are not calibrated probability distributions or guarantees.

The no-impact regime caps parent size at 100 shares and 1% of initial observed
top-ten depth on either side. Tested sizes are 0.25 and 1 share. Historical markets
never react to hypothetical trades. Passive orders and queue position are not
implemented. [Exact contract](docs/CONTRACT.md) · [Data](docs/DATA.md).

## Reproduce the registered study

The immutable original archive is included at `data/raw/btc.parquet`. Attribution
and a separately callable pinned downloader are in [data/README.md](data/README.md).
Normalization explicitly excludes settlement/winner fields from policy input.

```sh
python -m queuecraft.data data/raw/btc.parquet /tmp/queuecraft-sessions
queuecraft study /tmp/queuecraft-sessions --plan docs/STUDY_PLAN.json \
  --out /tmp/queuecraft-study
python -m tools.differential /tmp/queuecraft-sessions/*.csv \
  --out /tmp/queuecraft-differential.json
```

The split freezes entire chronological windows before validity rules:
26 development, 18 confirmation. Invalid snapshots and gaps remain explicit
invalidation records. The plan registers policies, fees, sizes, deadlines and
four assumptions before evaluation. Every attempt or exclusion is retained.
No policy was tuned after opening confirmation results.

The executed study contains **5,632 trials**, **32,914 fills** and **33,939 ledger
transitions**, independently reconciled. **All 48 confirmation comparisons are
unresolved.** Twenty-six change mean sign across assumptions, but uncertainty
prevents calling those established reversals. The receding-horizon heuristic
does not establish an advantage over immediate execution.

The registered initial-spread classifier placed all 44 windows in one category.
There are no ordinary-category windows, so ordinary-versus-stressed empirical
coverage remains a research gap. This result is retained, not relabeled after
evaluation. [Executed results](docs/study-results.json) ·
[Independent artifact review](evidence/study-artifact-review.json).

Signed implementation shortfall compares fills with the initial captured
midpoint, adds fees and the same fixed unfinished-lot penalty. Negative costs
can mean favorable price movement, not profit. Reports include completion,
tail costs, unfilled lots and paired market-window uncertainty. Correlated
windows on one day cannot supply independent multi-day evidence. See
[study plan](docs/STUDY_PLAN.json), [validation](docs/VALIDATION.md) and
[performance](docs/PERFORMANCE.md).

## Verify and extend

For source development, install editable so the native extension is available
alongside the source package:

```sh
python -m pip install -e '.[study]'
```

```sh
make test
make sanitize
make tsan
python -m unittest discover -s tests -v
python -m tools.differential examples/recorded.csv --out /tmp/differential.json
```

The oracle was implemented without reading native source. Tests compare every
book level and fill/accounting field, not just closing balances. SQL independently
joins fills to orders and checks all cumulative ledger transitions. Deliberate
missing/orphan ledger, bad-unit, duplicate-fill and future-timestamp mutations
must fail validation. Sanitizer availability depends on the platform.

`RawCapture` is a bounded append-only journal for original message bytes supplied
by an embedding read-only collector. Truncation or CRC failure requires a fresh
snapshot/session. No live collector or exchange-level continuity is claimed for
the bundled snapshot archive. Restoring an exported order means replaying its
input, policy and configuration through `queuecraft verify`; there is no durable
mid-run native checkpoint or crash-atomic matching service.

[Architecture](docs/ARCHITECTURE.md) · [Differences from existing projects](docs/DISTINCTION.md)
· [License](LICENSE) · [Data attribution](NOTICE.md) · [Owner walkthrough](docs/WALKTHROUGH.md).
