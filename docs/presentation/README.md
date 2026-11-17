# A recorded update before arrival

This deliberately small, synthetic example exercises current source 54c24eabf5513632775158a2fd391013dd39ae37. It changes only modeled latency, not the strategy or input. Nothing connects to an exchange.

## Run it

Install the current source with Python 3.11+, a C++20 compiler and the declared `study` extra. From the repository root, choose fresh output paths:

```sh
python -m pip install '.[study]'
queuecraft validate docs/presentation/input.csv
queuecraft simulate docs/presentation/input.csv --side sell --size 7 --policy immediate --recording-end-ns 7000000000 --deadline 4 --latency-ms 0 --fee-ppm 100 --out /tmp/queuecraft-zero
queuecraft simulate docs/presentation/input.csv --side sell --size 7 --policy immediate --recording-end-ns 7000000000 --deadline 4 --latency-ms 55 --fee-ppm 100 --out /tmp/queuecraft-delayed
queuecraft verify /tmp/queuecraft-zero
queuecraft verify /tmp/queuecraft-delayed
```

Open each `report.html` locally. The saved [zero-latency report](latency-0/report.html) and [55ms report](latency-55/report.html) are the actual CLI outputs. GitHub shows HTML source, so download the complete bundle to open them. Each links its original input, configuration and complete typed result.

## The exact account

The initial book has bids 100×4,99×6,98×1000 and ask 102×1000. The deeper level keeps this seven-lot parent within the engine's one-percent initial depth cap. At50ms an absolute update changes100-tick bid depth to 2. A later snapshot at 2 s is retained in the recording but cannot change this already-filled order. The independently declared recording end is 7 s; the deadline is 4 s.

| Modeled arrival | Fills | Gross tick×lot | Per-fill fees | Net cash delta | Inventory |
| --- | --- | --- | --- | --- | --- |
| 0ms | 4×100 +3×99 |697|1+1|695|−7lots|
|55ms|2×100 +5×99|695|1+1|693|−7lots|

Prices are integer ticks, quantities integer lots, money tick×lot units, not dollars. Fee100ppm is rounded upward independently for each fill. Cash is a signed delta account starting at zero. Unknown exchange times remain −1; this example uses synthetic capture timestamps. Both SQL reconciliations contain zero violations. The full exported configurations, including coverage and declared event tie order, remain beside each result.

## Stream to another process

```sh
queuecraft stream docs/presentation/input.csv --start-ns 0 --deadline-ns 4000000000 --recording-end-ns 7000000000 --side sell --size 7 --latency-ns 55000000 --fee-ppm 100 --collect --out /tmp/queuecraft-transitions.ndjson
```

The actual [NDJSON stream](transitions.ndjson) ends `complete`. All fills, orders and ledger values match the 55 ms batch export. Stream intent `max_quantity` uses its API default; batch CLI uses its own 10000-lot bound, so whole configuration objects intentionally differ. Streaming does not create a SQL-reconciled export directory and cannot resume a partial native simulation. Earlier records are provisional until terminal completion.

## Transfer, refusal and replay

Copy either five-file export directory to another path and run `queuecraft verify` there. Verification recomputes the full result and independently checks its account with DuckDB 1.4.3. It accepts JSON whitespace/key-order changes, but refuses boolean substitutions for integer fields. The executed [journey record](journey.json) captures successful fresh-process transfer, existing-directory refusal, insufficient-coverage refusal and typed tamper rejection without rewriting the saved artifact. Hashes bind bytes, not authenticity.

[Download worked-example.zip](worked-example.zip), extract it and run `python reopen.py` to verify member bytes and independently recompute the fill/fee/account arithmetic with the standard library. This lightweight check is not a replacement engine. Fresh native replay requires the full pinned source and installed QueueCraft with DuckDB; `queuecraft verify latency-55` then performs it from the extracted folder.

## SDK and scope

The existing [C++ consumer](../../tests/cpp/consumer.cpp) is compiled against an installed static library/header only; this pass actually produced `filled=3 cash=-1505 fees=2` in a separate synthetic buy. The separate [Python strategy consumer](../../examples/strategy.py) uses the public typed API. [Machine checks](machine-check.json) compare installed Python `run`, streaming records and both CLI results.

Historical recorded markets never react to hypothetical trades. No passive queue position is observed, no execution-quality claim follows from this two-case example, and the registered prospective study is not rerun here. Its negative/uncertain results, inherited sources and data licenses remain in the main documentation. The saved reports are evidence views, not a dashboard controlling an account.
