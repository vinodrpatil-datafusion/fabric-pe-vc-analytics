"""Limited Partners and LP commitments to funds."""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

from .lineage import LineageContext, attach_lineage
from .reference import (
    LP_DOMICILE_WEIGHTS,
    LP_DOMICILES,
    LP_TYPE_WEIGHTS,
    LP_TYPES,
)
from .scale import ScaleProfile


def _lp_name(lp_type: str, fake: Faker, rng: np.random.Generator) -> str:
    if lp_type == "Pension Fund":
        return f"{fake.state()} State Pension System"
    if lp_type == "Sovereign Wealth Fund":
        return f"{fake.country()} Sovereign Investment Authority"
    if lp_type == "Endowment":
        return f"{fake.last_name()} University Endowment"
    if lp_type == "Family Office":
        return f"{fake.last_name()} Family Office"
    if lp_type == "Fund of Funds":
        return f"{fake.last_name()} {fake.last_name()} FoF Partners"
    if lp_type == "Insurance":
        return f"{fake.last_name()} Mutual Insurance"
    return f"{fake.company()}"


def generate_lps(
    profile: ScaleProfile,
    rng: np.random.Generator,
    ctx: LineageContext,
    fake: Faker,
) -> pd.DataFrame:
    n = profile.n_lps
    lp_ids = [f"LP-{i:05d}" for i in range(1, n + 1)]
    types = rng.choice(LP_TYPES, size=n, p=LP_TYPE_WEIGHTS)
    domiciles = rng.choice(LP_DOMICILES, size=n, p=LP_DOMICILE_WEIGHTS)
    names = [_lp_name(t, fake, rng) for t in types]

    # AUM in millions, log-normal scaled by LP type
    aum_means = {
        "Pension Fund": 9.5,
        "Sovereign Wealth Fund": 11.0,
        "Endowment": 8.5,
        "Family Office": 7.0,
        "Fund of Funds": 8.0,
        "Insurance": 9.0,
    }
    aum = np.array([rng.lognormal(aum_means[t], 0.6) for t in types])
    aum = np.round(aum, 1)

    df = pd.DataFrame({
        "lp_id": lp_ids,
        "lp_name": names,
        "lp_type": types,
        "domicile": domiciles,
        "aum_m_usd": aum,
    })

    return attach_lineage(df, ctx, source_file="limited_partners.parquet")


def generate_commitments(
    funds_df: pd.DataFrame,
    lps_df: pd.DataFrame,
    profile: ScaleProfile,
    rng: np.random.Generator,
    ctx: LineageContext,
) -> pd.DataFrame:
    """Build LP commitments per fund.

    For each LP, choose a Poisson-distributed number of funds to commit to,
    then size each commitment realistically (small share of fund's committed capital).
    """
    rows = []
    fund_lookup = funds_df.set_index("fund_id")[["committed_capital_m", "currency"]].to_dict("index")
    fund_ids = funds_df["fund_id"].tolist()

    for lp_id in lps_df["lp_id"]:
        n_commit = max(1, int(rng.poisson(profile.avg_commitments_per_lp)))
        n_commit = min(n_commit, len(fund_ids))
        chosen = rng.choice(fund_ids, size=n_commit, replace=False)
        for fund_id in chosen:
            fund_info = fund_lookup[fund_id]
            # LP commitment: 0.5–8% of fund committed capital
            share = rng.uniform(0.005, 0.08)
            commit_m = round(fund_info["committed_capital_m"] * share, 2)
            rows.append({
                "lp_id": lp_id,
                "fund_id": fund_id,
                "commitment_m": commit_m,
                "currency": fund_info["currency"],
            })

    df = pd.DataFrame(rows)
    df["commitment_id"] = [f"COMM-{i:07d}" for i in range(1, len(df) + 1)]
    df = df[["commitment_id", "lp_id", "fund_id", "commitment_m", "currency"]]

    return attach_lineage(df, ctx, source_file="lp_commitments.parquet")
