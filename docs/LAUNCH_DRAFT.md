# Launch draft, not posted

I built QueueCraft, a small C++20/Python execution-research engine focused on a
question backtests often hide: does a policy ranking survive different timing
and available-liquidity assumptions?

It has exact tick/lot accounting, a real strategy callback API, independent
Python book/fill agreement and per-transition DuckDB checks. Its study compares
immediate, TWAP, liquidity-aware and receding-horizon policies under registered
scenarios, retaining unfinished orders and negative results.

The registered prospective archive contains licensed snapshot windows across
eight assets and four dates, with one reserved confirmation date. It does
not identify exchange event order or queue position, and this is not a profit
claim. The completed registered run has 66,720 executions and retained exclusions.
Most confirmation comparisons remain unresolved. The new horizon policy has
lower penalized cost but much more unfinished inventory, so it does not establish
execution superiority. The useful output is an inspectable stability map plus
replayable traces.

[Source](https://github.com/nazeeh111/QueueCraft) ·
[Versioned release](https://github.com/nazeeh111/QueueCraft/releases/tag/v0.1.0) ·
[Executed public verification](https://github.com/nazeeh111/QueueCraft/releases/download/v0.1.0/delivery-evidence.json).

Relevant audiences: C++ systems/replay engineering and market-microstructure
research discussions that permit project demonstrations. No outreach sent,
endorsement implied or adoption invented.
