# Data attribution

`raw/btc.parquet` is an unmodified archive published by **PolyOrderbooks (2026),
Polymarket Crypto 5-Minute Markets: 1-Second L2 Order Books**. It is licensed by
the publisher under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Source and license declaration:
https://huggingface.co/datasets/polyorderbooks/polymarket-crypto-5min-l2/blob/2e74c05ab8c0f5cc5379ca934c2abef857ef2a62/README.md

QueueCraft's derived session CSVs are normalization adaptations of that archive
and retain the same attribution and CC BY 4.0 license. Changes: select Up tokens,
filter to market intervals, convert decimal prices/sizes into checked tick/lot
integers, mark invalid/gapped snapshots with explicit invalidation events, and
freeze chronological development/confirmation membership. No settlement labels
are included in replay files. `raw/manifest.json` records the exact source hash.

`sessions-v1` is a retained rejected coarse-tick normalization attempt.
`sessions-v2` is the corrected normalization. See [DATA.md](../docs/DATA.md) for
limitations, clock semantics, exact assumptions and acquisition commands.

This data license is separate from QueueCraft's software license. Neither the
data publisher nor the exchange endorses QueueCraft. Publisher licensing is
provenance and does not guarantee upstream rights or exchange data completeness.
