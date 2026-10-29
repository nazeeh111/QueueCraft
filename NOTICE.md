# Attribution and scope

QueueCraft original code: MIT, copyright2026 nazeeh111.

The genuine BTC snapshot archive and its extracted example are separate data,
published by PolyOrderbooks under Creative Commons Attribution4.0 International.
Source: https://huggingface.co/datasets/polyorderbooks/polymarket-crypto-5min-l2
Pinned revision: 2e74c05ab8c0f5cc5379ca934c2abef857ef2a62.
License: https://creativecommons.org/licenses/by/4.0/ .
Changes: selected BTC Up-token columns, chronological market windows, exact
fixed-point normalization, invalidation records, first31second example.
Original full archive retained unchanged in data/raw/btc.parquet with provenance.
No affiliation with or endorsement by PolyOrderbooks or Polymarket.

The uploader's license is the recorded distribution basis, not an independent
legal determination of all underlying exchange rights. See docs/DATA.md.

Design references: Coinbase Exchange WebSocket channel semantics, HftBacktest
order-fill limitations. No source code was copied from those projects.
HftBacktest is not benchmarked here because matched input/event semantics are
unavailable for this snapshot archive. No performance superiority is claimed.

chronal, MarketObservatory and MarketWeave were inspected as existing work;
QueueCraft does not copy or rename their implementation. See docs/DISTINCTION.md.

Prospective 15-minute archive: PolyOrderbooks, Polymarket Crypto Up/Down Order
Books, Zenodo v1.0.1, DOI 10.5281/zenodo.22084977, CC BY 4.0. The original
updown_15m.parquet and publisher metadata are in data/15m-archive. Changes:
select Up outcome and quote arrays; normalize exact ticks/lots; reserve whole
UTC opening days; retain prefix-only operational quote/depth proxy labels and
explicit invalidations. Source DOI: https://doi.org/10.5281/zenodo.22084977 .
Raw SHA256: d86191506e416026f460338b1b238c628b3fcee37f468e646b3a2256bd0be959.
