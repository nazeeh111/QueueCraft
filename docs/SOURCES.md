# Primary sources consulted

- Coinbase Exchange [channel semantics](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels)
  and [best practices](https://docs.cdp.coinbase.com/exchange/websocket-feed/best-practices):
  absolute L2 replacement/update semantics and connection/slow-consumer considerations.
- Coinbase [market-data terms](https://www.coinbase.com/legal/market_data), updated
  August7,2026: current restrictions on outside dissemination and automated-system
  use made that feed unsuitable for this public artifact. No Coinbase data captured.
- HftBacktest [fill model limitations](https://hftbacktest.readthedocs.io/en/latest/order_fill.html)
  and [source](https://github.com/nkaz001/hftbacktest): replay does not change the
  historical market; market-by-price does not identify queue position. No matched
  benchmark is claimed.
- PolyOrderbooks [dataset license and limitations](https://polyorderbooks.com/datasets)
  and [pinned archive](https://huggingface.co/datasets/polyorderbooks/polymarket-crypto-5min-l2/tree/2e74c05ab8c0f5cc5379ca934c2abef857ef2a62):
  CC BY4.0 distribution, observed snapshots and one-sided/crossed-book limitations.
- Hyperliquid [academic archive](https://zenodo.org/records/18184441) and its
  [README](https://zenodo.org/records/18184441/files/README.md): a richer licensed
  alternative, rejected for this bounded initial build because the diff archive
  is about50GB and correct replay also requires initialization/timestamp joins.

Retrieved content was treated as evidence rather than execution instructions.
