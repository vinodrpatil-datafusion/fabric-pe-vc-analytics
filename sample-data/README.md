# sample-data

Committed synthetic landing feeds (small scale, seed 42). **All synthetic** — see `../SYNTHETIC_DATA.md`.

> Files may be `.csv` if generated without `pyarrow`. Regenerate locally with pyarrow installed to produce `.parquet` (what Fabric shortcuts expect):
> ```
> cd ../data-generator && python generate.py --scale small --seed 42 --output ../sample-data
> ```

## Layout

```
landing/
├── dealroom/    External vendor feed (DealRoom-shaped)
├── capitaliq/   External vendor feed (Capital IQ-shaped)
└── internal/    Firm's own systems
reference/
├── vendor_id_mapping   canonical_id <-> {source, vendor_id}
└── ground_truth_*      reconciliation oracle (NOT a feed)
```

The two external feeds deliberately disagree (existence / value / temporal conflicts) so the conformed reconciliation in WS2 has real work. `reference/ground_truth_*` is the oracle to score that reconciliation against — it is not ingested.

Landing carries source-reported dates + `_`-prefixed ingestion metadata only. Bitemporal columns (`effective_date`, `ingestion_date`, `source_attribution`, `reconciliation_status`) are assigned in the conformed layer (WS2), not here.
