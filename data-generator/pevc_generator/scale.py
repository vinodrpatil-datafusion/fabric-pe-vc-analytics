"""Scale profiles. Small is the committed sample target."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleProfile:
    name: str
    n_companies: int
    n_investors: int
    n_people: int
    n_internal_deals: int
    n_documents: int
    max_rounds_per_company: int


SMALL = ScaleProfile("small", n_companies=200, n_investors=120, n_people=400,
                     n_internal_deals=60, n_documents=150, max_rounds_per_company=5)
MEDIUM = ScaleProfile("medium", n_companies=800, n_investors=350, n_people=1500,
                      n_internal_deals=200, n_documents=600, max_rounds_per_company=6)
LARGE = ScaleProfile("large", n_companies=2500, n_investors=900, n_people=4500,
                     n_internal_deals=600, n_documents=1800, max_rounds_per_company=7)

PROFILES = {"small": SMALL, "medium": MEDIUM, "large": LARGE}
