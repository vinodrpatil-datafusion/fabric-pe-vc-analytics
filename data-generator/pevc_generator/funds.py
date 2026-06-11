"""Fund entity generation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .lineage import LineageContext, attach_lineage
from .reference import (
    FUND_CURRENCIES,
    FUND_CURRENCY_WEIGHTS,
    FUND_STRATEGIES,
    FUND_STRATEGY_WEIGHTS,
    GP_NAMES,
    LIFECYCLE_STAGES,
    STRATEGY_SIZE_PARAMS,
    VINTAGE_MAX,
    VINTAGE_MIN,
)
from .scale import ScaleProfile

CURRENT_YEAR = 2026


def _lifecycle_stage(vintage: int) -> str:
    age = CURRENT_YEAR - vintage
    for lo, hi, stage in LIFECYCLE_STAGES:
        if lo <= age < hi:
            return stage
    return "Winding Down"


def generate_funds(profile: ScaleProfile, rng: np.random.Generator, ctx: LineageContext) -> pd.DataFrame:
    n = profile.n_funds
    fund_ids = [f"FUND-{i:04d}" for i in range(1, n + 1)]

    strategies = rng.choice(FUND_STRATEGIES, size=n, p=FUND_STRATEGY_WEIGHTS)
    vintages = rng.integers(VINTAGE_MIN, VINTAGE_MAX + 1, size=n)
    currencies = rng.choice(FUND_CURRENCIES, size=n, p=FUND_CURRENCY_WEIGHTS)
    gps = rng.choice(GP_NAMES, size=n)

    # Target size from strategy-specific log-normal, in millions of base currency
    target_sizes = np.zeros(n)
    for i, strat in enumerate(strategies):
        mean_log, sigma = STRATEGY_SIZE_PARAMS[strat]
        target_sizes[i] = rng.lognormal(mean_log, sigma)
    target_sizes = np.round(target_sizes, 1)

    # Committed capital: 85–105% of target (oversubscribed funds exist)
    commit_ratio = rng.uniform(0.85, 1.05, size=n)
    committed = np.round(target_sizes * commit_ratio, 1)

    lifecycle = [_lifecycle_stage(int(v)) for v in vintages]

    df = pd.DataFrame({
        "fund_id": fund_ids,
        "fund_name": [f"{gp} Fund {rng.integers(1, 8)}" for gp in gps],
        "gp_name": gps,
        "strategy": strategies,
        "vintage": vintages.astype(int),
        "target_size_m": target_sizes,
        "committed_capital_m": committed,
        "currency": currencies,
        "lifecycle_stage": lifecycle,
    })

    return attach_lineage(df, ctx, source_file="funds.parquet")
