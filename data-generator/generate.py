"""CLI for the PE/VC synthetic data generator.

Usage:
    python generate.py --scale small --seed 42 --output ../sample-data
    python generate.py --scale medium --seed 42 --output /tmp/pevc-medium
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

from pevc_generator import LineageContext, PROFILES
from pevc_generator.companies import generate_companies
from pevc_generator.deals import generate_deals_valuations_cashflows
from pevc_generator.funds import generate_funds
from pevc_generator.lps import generate_commitments, generate_lps


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic PE/VC dataset.")
    parser.add_argument("--scale", choices=list(PROFILES.keys()), default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("../sample-data"))
    parser.add_argument(
        "--format",
        choices=["parquet", "csv", "both"],
        default="parquet",
        help="Output format. Default parquet for compact committable sample.",
    )
    args = parser.parse_args()

    profile = PROFILES[args.scale]
    args.output.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.seed)
    fake = Faker()
    Faker.seed(args.seed)

    ctx = LineageContext.new()

    print(f"[generator] scale={profile.name} seed={args.seed} batch_id={ctx.batch_id}")
    t0 = time.time()

    print("[1/5] funds…")
    funds_df = generate_funds(profile, rng, ctx)

    print(f"[2/5] limited partners ({profile.n_lps})…")
    lps_df = generate_lps(profile, rng, ctx, fake)

    print("[3/5] LP commitments…")
    commitments_df = generate_commitments(funds_df, lps_df, profile, rng, ctx)

    print("[4/5] portfolio companies…")
    companies_df = generate_companies(funds_df, profile, rng, ctx, fake)

    print(f"[5/5] deals, valuations, cashflows ({len(companies_df)} companies)…")
    deals_df, vals_df, cfs_df = generate_deals_valuations_cashflows(
        funds_df, companies_df, rng, ctx
    )

    outputs = {
        "funds": funds_df,
        "limited_partners": lps_df,
        "lp_commitments": commitments_df,
        "portfolio_companies": companies_df,
        "deals": deals_df,
        "valuations": vals_df,
        "cashflows": cfs_df,
    }

    print(f"\n[output] writing to {args.output.resolve()}")
    total_bytes = 0
    for name, df in outputs.items():
        if args.format in ("parquet", "both"):
            p = args.output / f"{name}.parquet"
            df.to_parquet(p, index=False, compression="snappy")
            sz = p.stat().st_size
            total_bytes += sz
            print(f"  {name:25s} rows={len(df):>7,d}  {sz/1024:>8.1f} KB  parquet")
        if args.format in ("csv", "both"):
            p = args.output / f"{name}.csv"
            df.to_csv(p, index=False)
            sz = p.stat().st_size
            if args.format == "csv":
                total_bytes += sz
            print(f"  {name:25s} rows={len(df):>7,d}  {sz/1024:>8.1f} KB  csv")

    elapsed = time.time() - t0
    print(f"\n[done] {total_bytes/1024/1024:.2f} MB in {elapsed:.1f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
