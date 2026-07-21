# data-generator (v2)

Generates synthetic **multi-source landing feeds** for the Investment Analytics domain, aligned to `../docs/data_model.md`. Produces controlled cross-source conflicts so the conformed-layer reconciliation (WS2) has real work.

See `../SYNTHETIC_DATA.md` for the full data contract, conflict model, and limitations.

## Quick start

```bash
pip install -r requirements.txt          # numpy, pandas, pyarrow
python generate.py --scale small --seed 42 --output ../sample-data
python validate_output.py
```

Writes **Parquet** when `pyarrow` is present, else **CSV** (Fabric shortcuts want Parquet — regenerate locally with pyarrow installed).

## Output tree

```
sample-data/
├── landing/
│   ├── dealroom/    companies funding_rounds investors investments
│   ├── capitaliq/   companies funding_rounds investors investments
│   └── internal/    people deals documents lp_documents lp_document_manifest
└── reference/
    ├── vendor_id_mapping        canonical_id <-> {source, vendor_id}
    └── ground_truth_*           reconciliation oracle (NOT a feed)
```

Maps to `../infrastructure/workspace_layout.md` → `landing_lakehouse` (as-built, present
in each of `pevc-dev`/`pevc-test`/`pevc-prod`; `ws-ingestion-dev` is the documented
production-target name).

## Entities → data_model.md

| Generated | data_model.md | Sourcing |
|---|---|---|
| companies | §1.1 | dealroom + capitaliq (reconciled) |
| funding_rounds | §1.2 | dealroom + capitaliq (reconciled) |
| investors | §1.3 | dealroom + capitaliq (reconciled) |
| investments | §1.4 | dealroom + capitaliq (reconciled) |
| people | §1.5 | internal |
| deals | §1.6 | internal |
| documents | §1.7 | internal |
| reconciliation_log | §1.8 | **not generated** — WS2 output |
| lp_documents | §1.9 | internal (templated from canonical ground truth, DD-17) |
| lp_document_manifest | §1.10 | internal (citation ground truth for `lp_documents`) |

## Scale

| Scale | Companies | Investors | People | Rounds (approx) | Size |
|---|---|---|---|---|---|
| small | 200 | 120 | 400 | ~450 | ~1.2 MB |
| medium | 800 | 350 | 1500 | ~1800 | ~5 MB |
| large | 2500 | 900 | 4500 | ~5600 | ~16 MB |

`lp_documents`/`lp_document_manifest` aren't a fixed scale count — they derive organically
from fund-type investors' actual investments (one capital call notice per participation,
one memo per exit, up to `MAX_LETTER_QUARTERS` quarterly letters per fund). At `small`,
that's ~1,570 documents / ~5,350 manifest rows.

## Package layout

```
pevc_generator/
├── io_utils.py    Parquet/CSV writer, JSON-string nested cols
├── names.py       Curated PE/VC name banks (no faker dependency)
├── reference.py   Vocabularies + SOURCE_PROFILES (conflict config)
├── lineage.py     Landing metadata
├── scale.py       small / medium / large
├── canonical.py   Ground-truth oracle (the 'real world')
├── sources.py     Project oracle -> per-source feeds with conflicts
├── internal.py    Internal pipeline (deals) + documents
└── lp_documents.py LP document corpus: quarterly letters, capital calls, memos (DD-17)
```

## Tuning conflicts

Edit `SOURCE_PROFILES` in `reference.py` (`coverage`, `announce_lag_*`, `amount_noise_*`, `edge_drop_p`, …). Re-run `validate_output.py` to see the resulting rates.
