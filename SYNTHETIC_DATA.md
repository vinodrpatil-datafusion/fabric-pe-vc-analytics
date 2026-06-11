# Synthetic Data Notice

> All data in `/sample-data/` and all output produced by `/data-generator/` is **synthetic**. It does not represent any real fund, LP, company, or transaction. Names, geographies, valuations, and performance figures are generated procedurally with no reference to real-world entities.

## Why synthetic

This is a reference architecture for PE/VC investment analytics on Microsoft Fabric. Real PE data (Preqin, PitchBook, Refinitiv) is licence-restricted and cannot be redistributed. Public alternatives like SEC EDGAR do not map cleanly to the PE/VC schema (funds, LPs, commitments, NAV marks, exits).

The decision was made to:
- Generate fully synthetic data, clearly labelled
- Make the **schema realism** the credibility gate, not the row values
- Calibrate distributions against publicly available PE industry data (Bain Global PE Report, Cambridge Associates benchmarks, McKinsey Global Private Markets Review) to make the dataset *plausible* without copying any specific source

## What is modelled

Seven entities with referential integrity:

| Entity | Description | Small-scale row count |
|---|---|---|
| `funds` | Fund vehicles managed by GPs | 25 |
| `limited_partners` | LP investors (pensions, SWFs, endowments, etc.) | 80 |
| `lp_commitments` | LP capital commitments to funds (M:N) | ~200 |
| `portfolio_companies` | Investee companies held by funds | ~270 |
| `deals` | Primary, follow-on, and exit transactions | ~600 |
| `valuations` | Quarterly NAV marks per holding | ~5,500 |
| `cashflows` | Capital calls and distributions | ~600 |

## Distribution calibration

Distributions are deliberately skewed to PE reality rather than uniform-random. Key calibrations:

- **Fund strategy weights:** Buyout 45% / VC 30% / Growth 20% / Secondaries 5%
- **Fund size by strategy (log-normal medians):** Buyout ~$1.5B, Growth ~$500M, VC ~$250M, Secondaries ~$2B
- **LP type mix:** Pension Fund 32% / Family Office 20% / Endowment 15% / FoF 13% / Insurance 10% / SWF 10%
- **Sector concentration:** Information Technology 28% / Healthcare 18% (the two dominant PE sectors)
- **Geography:** North America ~56%, Europe ~25%, rest of world ~19%
- **Outcomes:** Median exit multiple ~2.5x (log-normal with fat right tail); write-off rate ~10–15% at maturity
- **J-curve:** Early-quarter NAVs dip slightly before climbing toward final outcome

**Caveat:** At small scale (n=25 funds), random variance can push observed mixes 5–15 percentage points off target. This is expected. The generator converges to calibrated weights at medium and large scale.

## Lineage metadata

Every row carries seven metadata columns from generation, surviving Bronze → Silver → Gold promotion:

| Column | Type | Purpose |
|---|---|---|
| `_record_id` | UUID | Unique row identifier |
| `_source_system` | string | Fixed: `pevc-synthetic-generator` |
| `_source_file` | string | Generator output filename for this row |
| `_ingestion_ts` | timestamp | Generator run timestamp (UTC) |
| `_batch_id` | UUID | Generator run identifier (one batch ID per run, shared across all entities) |
| `_data_version` | string | Schema version (currently `v1.0.0`) |
| `_is_synthetic` | bool | Always `true` — explicit honesty flag |

These columns are designed to align with Microsoft Purview classification and lineage capture in later workstreams.

## What is NOT modelled (deliberately)

The following are out of scope for v1 to keep the schema clean and the generator tractable. Some may be added in later versions:

- **Co-investments** — companies belong to exactly one fund (no shared holdings)
- **Side letters and MFN clauses** — LP-fund relationships are simple commitments
- **Multi-currency LP commitments to single-currency funds** — LP commitments inherit fund currency
- **Bridge financing and warehouse facilities**
- **Carry waterfalls and GP economics** — only LP-side cashflows are modelled
- **Tranches within deals**
- **Secondary transactions between LPs** — LP commitments are static

## Reproducibility

Output is deterministic given a fixed `--seed`. The committed sample uses `seed=42`.

```bash
cd data-generator
python generate.py --scale small --seed 42 --output ../sample-data
```

## Honest limitations

1. **Small-sample variance.** The committed small dataset (n=25 funds) shows ~15% deviation from target strategy weights due to random sampling. Use `--scale medium` or `--scale large` for cleaner distributions.
2. **TVPI slightly elevated.** Median fund TVPI in the small sample runs ~2.5–3.0x; real PE median is closer to 1.8–2.2x. Acceptable for demonstration purposes; the log-normal multiplier parameters in `deals.py` can be tuned down for stricter realism.
3. **No vintage-cohort correlation in outcomes.** Real PE shows clear vintage effects (e.g. 2006 vintages underperformed); this generator treats outcomes as independent of vintage. Adding a vintage performance overlay is a v2 candidate.
4. **GP and LP names are fictional.** Any resemblance to real firms is coincidental.

## Licence

Code and synthetic data: MIT (see `LICENSE`).
