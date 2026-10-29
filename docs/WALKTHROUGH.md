# Owner walkthrough

1. Install from the pinned release and run the README quickstart. Open the new
   report and inspect each order's observation, arrival and acknowledgement.
2. Run the same command with size 50 and a new destination. Compare the actual
   fresh fill trace and cash delta, then run `queuecraft verify` on both folders.
3. Try `--latency-ms 1000`, `--fee-ppm 2000`
   and `--liquidity-ppm 100000`. These are declared assumptions, not estimates
   of actual venue latency or dynamic fees.
4. Open the study report. Filter confirmation, buy/sell and a policy pair. A
   sign reversal in means can still be statistically unresolved. Inspect
   completion and unfilled lots before interpreting a low penalized cost.
5. Run the separate strategy example from outside the source tree. Change its
   callback while keeping the same parent and scenario; it must return the
   installed public `OrderRequest`, not touch private native handles.
6. Reproduce the data normalization and differential test. Keep all invalidations
   and exclusions. Upgrade to a new registered study for new hypotheses; do
   not tune on the current confirmation region and call it unobserved again.

Keep `input.csv`, `config.json`, `result.json` and the source version together.
`verify` reruns them and independently reconciles SQL. Outputs refuse overwrite.
The HTML is a saved evidence view; a fresh order is computed through the CLI.
