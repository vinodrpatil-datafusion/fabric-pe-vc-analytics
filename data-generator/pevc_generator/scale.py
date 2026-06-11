"""Scale profiles for generator output.

Small profile is the committed sample target (~10 MB compressed Parquet).
Medium and large are runtime options for richer demos; not committed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleProfile:
    name: str
    n_funds: int
    n_lps: int
    avg_commitments_per_lp: float
    companies_per_fund_mean: float
    companies_per_fund_std: float
    quarters_history: int  # max NAV history depth per company

    @property
    def expected_companies(self) -> int:
        return int(self.n_funds * self.companies_per_fund_mean)


SMALL = ScaleProfile(
    name="small",
    n_funds=25,
    n_lps=80,
    avg_commitments_per_lp=2.5,
    companies_per_fund_mean=12.0,
    companies_per_fund_std=3.5,
    quarters_history=40,
)

MEDIUM = ScaleProfile(
    name="medium",
    n_funds=80,
    n_lps=250,
    avg_commitments_per_lp=3.2,
    companies_per_fund_mean=15.0,
    companies_per_fund_std=4.0,
    quarters_history=40,
)

LARGE = ScaleProfile(
    name="large",
    n_funds=250,
    n_lps=600,
    avg_commitments_per_lp=4.0,
    companies_per_fund_mean=18.0,
    companies_per_fund_std=5.0,
    quarters_history=40,
)

PROFILES = {"small": SMALL, "medium": MEDIUM, "large": LARGE}
