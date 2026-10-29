# Existing projects and alternatives

Inspection2026-10-29, originals read-only:

| Project | Inspected evidence | Boundary |
| --- | --- | --- |
| chronal | local8db6d44 execution_diagnostics.py and current public README | daily cash-aware portfolio/intent research; explicitly no order book |
| MarketObservatory | local engine.py and current public README; local Git object alternate broken | price snapshots, aligned returns and allocations; no simulated execution |
| MarketWeave | localfd81992 feed normalizer/router and local SDK execution-price tests; remote README path404 | market/exchange adapters and snapshot sweep pricing; no independently verified deterministic event/accounting core |

QueueCraft adds a C++20 single-writer transaction engine, exact integer book and
ledger agreement against independently written Python, consumed liquidity across
events, delayed observation/arrival/acknowledgement, a policy callback SDK and a
registered scenario-stability study. The real archive is snapshot-only, so real
intersnapshot exchange ordering remains unidentified. Controlled S/U/G streams
test the implemented event protocol separately.

HftBacktest is the closest mature execution-replay reference. Its documentation
explicitly describes small-order/no-impact and market-by-price queue-model
limitations. QueueCraft currently implements marketable IOC orders only and no
passive queue estimates. Comparing speed or fills against HftBacktest without
matching timestamp, depth, consumption, fee and fill semantics would mislead.

Python-only implementation was considered, and retained as the slow oracle.
Native C++ owns production state/overflow/accounting; Python owns registered
scheduling and analysis. std::map with transactional copies favors auditability
before optimization; measured allocation costs remain visible.
