# Owner walkthrough

The current revision is local while publication approval and public checks remain
pending. Start from this source checkout; use the pinned release once verified.

1. Follow the README install and quickstart. Keep the supplied recording metadata
   with the input. Open the fresh report and inspect each order's observation,
   decision, arrival and acknowledgement. Recorded book events remain separate
   from modeled fills and consumed liquidity.
2. Repeat with `--size 50` and a fresh destination. Compare the new fill trace and
   cash delta. Run `queuecraft verify` on both folders to recompute each order
   and check every transition independently with DuckDB.
3. Try `--latency-ms 1000`, `--fee-ppm 2000` or `--liquidity-ppm 100000`.
   These declare assumptions; they do not estimate actual venue latency or fees.
   Recording coverage remains fixed when the order changes.
4. Reproduce the registered preparation/study commands. To reproduce the measured
   compute mode exactly, supply the saved `calibration.json`. Recalibration on a
   different desktop is a different timing sensitivity experiment. Policies never
   receive the evaluation-only common benchmark or future payloads.
5. Open the study report. Filter confirmation and a policy pair or side. Check
   ordinary/stressed quote groups, completion, unfinished lots and cost tails.
   Lower penalized cost alone is not evidence of better complete execution.
   Window intervals are conditional on correlated data; the single confirmation
   date cannot provide independent-day uncertainty.
6. Copy the separate strategy example and CSV outside the checkout and run it
   with the installed environment. Change its callback while keeping parent and
   scenario fixed. It uses public `Observation` and `OrderRequest` types.
7. Register a new study before changing policies or hypotheses after confirmation
   results. Preserve invalidations, failed attempts, all exclusions and the prior
   five-minute experiment. Do not reuse observed confirmation as an unseen test.

Keep `input.csv`, `config.json`, `result.json` and source version together.
`verify` replays the complete artifact; output folders refuse overwrite. The
HTML is a saved evidence view. Fresh order computation runs through the CLI.

`tools/record_demo.py --python /path/to/installed/python --source /path/to/checkout
--out /tmp/fresh-demo` records actual installed executions, changed orders and
SQL replay in asciinema v2 format. Commands are scripted; output and elapsed
timing are real, without simulated typing. View `docs/demo.cast` with a compatible
local player. No separate API, broker connection or paid service is required.
