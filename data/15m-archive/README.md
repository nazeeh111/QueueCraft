# Prospective 15-minute archive

Publisher: PolyOrderbooks. Frozen Zenodo version 1.0.1, record 22084977,
[DOI 10.5281/zenodo.22084977](https://doi.org/10.5281/zenodo.22084977).
The publisher licenses this data under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Original Parquet bytes, publisher README/metadata and acquisition hashes are retained.

Both outcome tokens and future resolution fields exist in the original file.
Only the explicit Up-token quote projection enters normalization. Resolution
labels never enter the strategy API. Capture times do not establish exchange
or network receive times, and collector sparsity is not proof of message loss.

Preparation reserves whole opening UTC days before validity filters. All 265
window attempts remain in the manifest, including exclusions. Parents start
60 seconds after 15-minute market opening. The explicit recording bound is a
declared 90-second extraction interval, independent of the last payload.
Operational stress means wide quotes or low development-relative depth; it is
not an external crisis classification. The raw file is a randomly selected set
of resolved markets, not an exhaustive or consecutive market-day tape.

Original and transformed data retain their separate CC BY attribution. MIT
licenses QueueCraft software, not a new ownership claim over market data.
