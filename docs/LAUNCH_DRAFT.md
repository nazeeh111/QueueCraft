# Launch draft, not posted

I built QueueCraft, a small C++20/Python execution-research engine focused on a
question backtests often hide: does a policy ranking survive different timing
and available-liquidity assumptions?

It has exact tick/lot accounting, a real strategy callback API, independent
Python book/fill agreement and per-transition DuckDB checks. Its study compares
immediate, TWAP, liquidity-aware and receding-horizon policies under registered
scenarios, retaining unfinished orders and negative results.

The bundled archive is licensed, imperfect snapshot data from one day. It does
not identify exchange event order or queue position, and this is not a profit
claim. The useful output is an inspectable stability map plus replayable traces.

Source and versioned artifacts: https://github.com/nazeeh111/QueueCraft

Relevant audiences: C++ systems/replay engineering and market-microstructure
research discussions that permit project demonstrations. No outreach sent,
endorsement implied or adoption invented.
