"""Portfolio company generation, with realistic sector/geo skew."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from .lineage import LineageContext, attach_lineage
from .reference import (
    COMPANY_COUNTRIES,
    COMPANY_COUNTRY_WEIGHTS,
    SECTOR_WEIGHTS,
    SECTORS,
)
from .scale import ScaleProfile


CURRENT_DATE = date(2026, 5, 13)


def _suffix_for_sector(sector: str, rng: np.random.Generator) -> str:
    suffixes = {
        "Information Technology": ["Labs", "Systems", "AI", "Cloud", "Software", "Networks"],
        "Healthcare": ["Health", "Therapeutics", "Bio", "Medical", "Diagnostics", "Pharma"],
        "Financials": ["Capital", "Financial", "Lending", "Markets", "Insurance"],
        "Consumer Discretionary": ["Brands", "Retail", "Goods", "Lifestyle"],
        "Industrials": ["Industries", "Manufacturing", "Logistics", "Engineering"],
        "Communication Services": ["Media", "Communications", "Networks"],
        "Consumer Staples": ["Foods", "Brands", "Consumer"],
        "Energy": ["Energy", "Power", "Resources"],
        "Materials": ["Materials", "Chemicals"],
        "Real Estate": ["Properties", "Realty"],
        "Utilities": ["Utilities", "Power"],
    }
    return rng.choice(suffixes.get(sector, ["Inc"]))


def generate_companies(
    funds_df: pd.DataFrame,
    profile: ScaleProfile,
    rng: np.random.Generator,
    ctx: LineageContext,
    fake: Faker,
) -> pd.DataFrame:
    """One company belongs to exactly one fund (primary holder).

    Co-investments exist in reality but are omitted for clean v1 modelling.
    """
    rows = []
    company_idx = 1

    for _, fund in funds_df.iterrows():
        # Number of companies in this fund
        n = int(max(3, rng.normal(profile.companies_per_fund_mean, profile.companies_per_fund_std)))
        for _ in range(n):
            sector = rng.choice(SECTORS, p=SECTOR_WEIGHTS)
            country = rng.choice(COMPANY_COUNTRIES, p=COMPANY_COUNTRY_WEIGHTS)
            base_name = fake.last_name()
            suffix = _suffix_for_sector(sector, rng)
            company_name = f"{base_name} {suffix}"

            founded = int(rng.integers(max(1990, fund["vintage"] - 12), fund["vintage"] + 2))
            # Entry date: somewhere in fund's investment period (years 0–4 from vintage)
            entry_offset_days = int(rng.integers(0, 4 * 365))
            entry_date = date(int(fund["vintage"]), 1, 1) + timedelta(days=entry_offset_days)

            # Exit / status logic
            age = (CURRENT_DATE - entry_date).days / 365.25
            if age > 8:
                # Mature hold: most exit, some write off, few still active
                roll = rng.random()
                if roll < 0.65:
                    status = "Exited"
                    exit_offset = rng.integers(4 * 365, min(int(age * 365), 10 * 365))
                    exit_date = entry_date + timedelta(days=int(exit_offset))
                elif roll < 0.80:
                    status = "Written Off"
                    exit_offset = rng.integers(2 * 365, 6 * 365)
                    exit_date = entry_date + timedelta(days=int(exit_offset))
                else:
                    status = "Active"
                    exit_date = None
            elif age > 4:
                roll = rng.random()
                if roll < 0.30:
                    status = "Exited"
                    exit_offset = rng.integers(3 * 365, int(age * 365))
                    exit_date = entry_date + timedelta(days=int(exit_offset))
                elif roll < 0.40:
                    status = "Written Off"
                    exit_offset = rng.integers(2 * 365, int(age * 365))
                    exit_date = entry_date + timedelta(days=int(exit_offset))
                else:
                    status = "Active"
                    exit_date = None
            else:
                # Young hold: mostly active, small write-off rate
                roll = rng.random()
                if roll < 0.05:
                    status = "Written Off"
                    exit_offset = rng.integers(1 * 365, max(2 * 365, int(age * 365)))
                    exit_date = entry_date + timedelta(days=int(exit_offset))
                else:
                    status = "Active"
                    exit_date = None

            rows.append({
                "company_id": f"CO-{company_idx:05d}",
                "company_name": company_name,
                "fund_id": fund["fund_id"],
                "sector": sector,
                "country": country,
                "founded_year": founded,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "status": status,
            })
            company_idx += 1

    df = pd.DataFrame(rows)
    return attach_lineage(df, ctx, source_file="portfolio_companies.parquet")
