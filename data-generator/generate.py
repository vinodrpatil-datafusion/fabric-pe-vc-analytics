"""CLI for the PE/VC investment-analytics synthetic generator (v2).

Output tree:
  <output>/
  ├── landing/
  │   ├── dealroom/   companies, funding_rounds, investors, investments
  │   ├── capitaliq/  companies, funding_rounds, investors, investments
  │   └── internal/   people, deals, documents, lp_documents, lp_document_manifest
  └── reference/
      ├── ground_truth_*  (oracle for reconciliation scoring; NOT a feed)
      └── vendor_id_mapping

Usage:
    python generate.py --scale small --seed 42 --output ../sample-data
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pevc_generator import LineageContext, PROFILES
from pevc_generator import reference as R
from pevc_generator.canonical import generate_canonical
from pevc_generator.conflicts import derive_expected_conflicts
from pevc_generator.internal import generate_internal
from pevc_generator.io_utils import OUTPUT_EXT, write_table
from pevc_generator.lineage import attach_landing_lineage
from pevc_generator.lp_documents import generate_lp_documents
from pevc_generator.sources import project_sources

# JSON-serialized (nested) columns per entity
JSON_COLS = {
    "companies": ["sector_taxonomy"],
    "funding_rounds": ["lead_investor_vendor_ids"],
    "investors": ["geographic_focus", "sector_focus", "stage_focus"],
    "investments": [],
    "people": ["current_affiliations", "historical_affiliations", "education", "notable_prior_companies"],
    "deals": ["stage_history"],
    "documents": ["subject_company_ids", "subject_deal_ids"],
    "gt_companies": ["name_history", "sector_taxonomy", "headquarters"],
    "gt_funding_rounds": ["lead_investor_ids"],
    "gt_investors": ["geographic_focus", "sector_focus", "stage_focus"],
    "gt_investments": [],
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic PE/VC landing feeds.")
    ap.add_argument("--scale", choices=list(PROFILES.keys()), default="small")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, default=Path("../sample-data"))
    args = ap.parse_args()

    profile = PROFILES[args.scale]
    rng = np.random.default_rng(args.seed)
    ctx = LineageContext.new()
    t0 = time.time()

    print(f"[generator v2] scale={profile.name} seed={args.seed} format={OUTPUT_EXT} batch={ctx.batch_id[:8]}")

    print("[1/5] canonical ground truth…")
    canonical = generate_canonical(profile, rng)

    print("[2/5] projecting source feeds with conflicts…")
    feeds = project_sources(canonical, rng)

    print("[3/5] internal feed (deals, documents, people)…")
    internal = generate_internal(canonical, profile, rng)

    print("[4/5] LP document corpus…")
    lp_docs = generate_lp_documents(canonical, rng)

    print(f"[5/5] writing to {args.output.resolve()}")
    landing = args.output / "landing"
    reference = args.output / "reference"

    total = 0
    # External source feeds
    for src in R.EXTERNAL_SOURCES:
        for entity in ("companies", "funding_rounds", "investors", "investments"):
            df = pd.DataFrame(feeds[src][entity])
            df = attach_landing_lineage(df, ctx, source_system=src, source_file=f"{entity}.{OUTPUT_EXT}")
            p = write_table(df, landing / src, entity, json_cols=JSON_COLS.get(entity))
            total += p.stat().st_size
            print(f"  landing/{src}/{entity:16s} rows={len(df):>6,d}")

    # Internal feed
    for entity in ("people", "deals", "documents"):
        rows = internal[entity] if entity in internal else canonical[entity]
        df = pd.DataFrame(rows)
        df = attach_landing_lineage(df, ctx, source_system=R.SOURCE_INTERNAL, source_file=f"{entity}.{OUTPUT_EXT}")
        p = write_table(df, landing / "internal", entity, json_cols=JSON_COLS.get(entity))
        total += p.stat().st_size
        print(f"  landing/internal/{entity:14s} rows={len(df):>6,d}")

    # LP document corpus (DD-17) -- also internal source: the firm's own record
    # of what was sent to LPs, not a third-party feed.
    for entity in ("lp_documents", "lp_document_manifest"):
        df = pd.DataFrame(lp_docs[entity])
        df = attach_landing_lineage(df, ctx, source_system=R.SOURCE_INTERNAL, source_file=f"{entity}.{OUTPUT_EXT}")
        p = write_table(df, landing / "internal", entity, json_cols=JSON_COLS.get(entity))
        total += p.stat().st_size
        print(f"  landing/internal/{entity:14s} rows={len(df):>6,d}")

    # vendor_id_mapping
    df_map = pd.DataFrame(feeds["vendor_id_mapping"])
    p = write_table(df_map, reference, "vendor_id_mapping")
    total += p.stat().st_size
    print(f"  reference/vendor_id_mapping       rows={len(df_map):>6,d}")

    # expected_conflicts ledger (oracle for WS2 reconciliation scoring)
    ledger = derive_expected_conflicts(canonical, feeds)
    df_led = pd.DataFrame(ledger)
    p = write_table(df_led, reference, "expected_conflicts")
    total += p.stat().st_size
    print(f"  reference/expected_conflicts      rows={len(df_led):>6,d}")

    # ground truth oracle (clearly labelled, not a feed)
    for entity in ("companies", "funding_rounds", "investors", "investments", "people"):
        df = pd.DataFrame(canonical[entity])
        # drop hidden helper cols
        df = df[[c for c in df.columns if not c.startswith("_")]]
        gtname = f"ground_truth_{entity}"
        jc = JSON_COLS.get(f"gt_{entity}", JSON_COLS.get(entity, []))
        p = write_table(df, reference, gtname, json_cols=jc)
        total += p.stat().st_size

    print(f"\n[done] {total/1024/1024:.2f} MB in {time.time()-t0:.1f}s  ({OUTPUT_EXT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
