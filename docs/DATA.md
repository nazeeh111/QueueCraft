# Recorded-data provenance and limits

The local integration archive is the original `btc.parquet` published by
PolyOrderbooks, frozen at Hugging Face revision
`2e74c05ab8c0f5cc5379ca934c2abef857ef2a62`. Its exact SHA256 is
`1dde1a3be9f1159aec12d7c5b7fddbc912d2e88d65af093adce0c2802f05452f`.
The [publisher's dataset card](https://huggingface.co/datasets/polyorderbooks/polymarket-crypto-5min-l2/blob/2e74c05ab8c0f5cc5379ca934c2abef857ef2a62/README.md)
states CC BY 4.0. Attribution: **PolyOrderbooks (2026), Polymarket Crypto
5-Minute Markets: 1-Second L2 Order Books**. QueueCraft normalizes and filters this
recording; it is not affiliated with PolyOrderbooks or Polymarket. The uploader's
license establishes provenance; it is not a legal guarantee of upstream rights.

The full publisher mirror covers 352 short markets in less than four hours on
one day. The acquired BTC file has 26,068 rows and 44 distinct market windows.
These are not 44 independent days. The publisher acknowledges collector message
loss, crossed books and periodic REST replacement of its state. A local replay
can reproduce this recording, not certify the exchange's original full event
stream. Repeated snapshots contain no proof of replenishment or queue identity.

`tools/acquire_data.py` downloads at most 64 MiB, creates the raw file exclusively,
checks its pinned hash, and appends each acquisition result to a journal. A
failed partial download remains visible for inspection. Reruns never overwrite
it silently. The initial integration download used bounded curl and a verified
exclusive promotion; both the sandbox DNS failure and successful download are
retained in `data/raw/acquisition-attempts.jsonl`.

## Normalization and frozen split

Run `python -m queuecraft.data data/raw/btc.parquet data/sessions-v2` into a new
destination. The input remains untouched. Entire Up-token market windows are
ordered chronologically by opening time and assigned 60% development, 40%
confirmation **before** validity filtering. The manifest freezes source and
normalized SHA256 hashes, split membership, every window and invalidation reason.
Down tokens are not independent market sessions and are omitted to avoid
duplicating the same binary market. Both buy and sell intents can use Up books.

Only explicit ladder fields, identifiers and capture times enter normalization.
Settlement winner labels never enter replay or strategy observations. Replay uses
the interval from market opening through just before settlement. Preopening or
postsettlement observations remain in raw evidence and are counted in the manifest.

Each valid snapshot is an atomic `S` replacement. Tick size is 0.001 USD/share and
lot size 0.01 share; one money unit is 0.00001 USD. Nonintegral tick/lot values are
rejected, never rounded. Crossed/locked, empty, misaligned, duplicate-level and
out-of-range snapshots become `G` invalidations. Capture gaps exceeding five
seconds create an invalidation at the five-second threshold; a later valid
snapshot explicitly resynchronizes. This threshold bounds modeled observation
staleness and does not detect every dropped exchange update.

`exchange_ns=-1` means unknown. The CSV `receive_ns` field is populated from
recorded capture time solely as the simulation's observation timeline. It is not
an actual network arrival measurement. No latency calibration is possible here.

The attempted `sessions-v1` used a 0.01 price tick and consequently invalidated
695 snapshots containing genuine finer price increments. It is retained as a
rejected normalization attempt. `sessions-v2` corrects the tick after inspecting
raw price precision, before policy tuning. Quantity precision remains 0.01 share.

## Rejected routes

The current [Coinbase Market Data Terms](https://www.coinbase.com/legal/market_data)
restrict public dissemination of derived research as well as raw data. Its public
WebSocket therefore was not captured. The research archive
[An Open Book](https://zenodo.org/records/18184441) has an explicit CC BY 4.0
[README](https://zenodo.org/records/18184441/files/README.md), but its 49.6 GB
book-diff bundle exceeds this bounded first integration. No archive was relabeled
as observed exchange event continuity. General market or profitability conclusions
remain unsupported by this integration sample.

A conservative capture timeout is not proof of lost exchange messages. The
collector can be sparse when books do not change. QueueCraft treats a recorded
observation gap above five seconds as unknown state under its declared watchdog
rule, invalidating until the next full snapshot. This can reject quiet periods;
absence of rows is not relabeled as an observed exchange sequence gap.


## Registered 15-minute protocol

The five-minute experiment above is preserved as a prior attempt. The current
protocol uses a distinct frozen 15-minute archive, all eight assets, and four
whole opening UTC dates. [Source and attribution](../data/15m-archive/README.md).
Six preparation tests check chronological day separation, development-only
thresholds, future-label exclusion, prefix isolation and terminal watchdogs.

Parent start is opening +60 seconds. Recording end is the declared opening
+90-second extraction boundary, independently supplied to every simulator entry
point. The raw archive covers the wider contract window; extraction does not
infer its bound from the final retained payload. A five-second capture watchdog,
also used for execution staleness, invalidates quiet periods until a fresh full
snapshot. These are archive-coverage assumptions, not observed network liveness.

Operational stress means a parent-prefix spread above 10 ticks or minimum
bid/ask top-ten depth below the development lower quartile (44,592 lots).
Classification never uses policy costs, winner or resolution. All 265 window
attempts remain identifiable; 209 have a valid parent prefix, including 12
ordinary and 21 stressed windows on the reserved confirmation date. Asset/date
labels, invalidations, overlap checks and shared order-cap exclusions are retained.
See the [registered protocol](PROSPECTIVE_PLAN.json). A random publisher sample
of resolved contracts is not a complete market-day tape or evidence of exchange
continuity. The single confirmation date limits generalization.
