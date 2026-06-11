"""Reference data, controlled vocabularies, and conflict-injection config.

Vocabularies align with data_model.md enums. Conflict rates drive the
multi-source projection so WS2's 02_reconciliation.py has realistic
value/temporal/existence disagreements to surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Sector taxonomy (data_model 1.1: multi-tag) ---
# Grouped for name generation; tags are the leaf labels stored in sector_taxonomy[].
SECTOR_GROUPS = {
    "Information Technology": ["SaaS", "AI/ML", "Cybersecurity", "DevTools", "Data Infrastructure", "Fintech Infra"],
    "Healthcare": ["Digital Health", "Biotech", "Medical Devices", "Diagnostics", "Genomics"],
    "Financials": ["Fintech", "Payments", "Lending", "InsurTech", "WealthTech"],
    "Consumer": ["Consumer Apps", "E-commerce", "Marketplace", "Food & Bev", "Gaming"],
    "Industrials": ["Robotics", "Supply Chain", "Manufacturing Tech", "Logistics"],
    "Energy": ["Energy Storage", "Grid Tech", "Oil & Gas Tech"],
    "Climate": ["Carbon Capture", "Clean Energy", "Sustainability"],
    "Mobility": ["AV/Autonomy", "EV", "Micromobility", "Fleet"],
}
SECTOR_GROUP_NAMES = list(SECTOR_GROUPS.keys())
SECTOR_GROUP_WEIGHTS = [0.30, 0.18, 0.14, 0.12, 0.09, 0.06, 0.06, 0.05]

# --- Round types (data_model 1.2) ---
ROUND_TYPES = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Bridge", "Growth"]
# Typical progression weights for a company's first round
FIRST_ROUND_WEIGHTS = {"Pre-Seed": 0.25, "Seed": 0.45, "Series A": 0.20, "Bridge": 0.05, "Growth": 0.05}

INSTRUMENT_TYPES = ["Equity", "Convertible Note", "SAFE"]
INSTRUMENT_WEIGHTS = [0.62, 0.20, 0.18]

CURRENCIES = ["USD", "EUR", "GBP"]
CURRENCY_WEIGHTS = [0.68, 0.22, 0.10]

# --- Investor types (data_model 1.3) ---
INVESTOR_TYPES = [
    "vc_fund", "pe_fund", "corporate_vc", "family_office",
    "sovereign_fund", "angel", "accelerator", "strategic",
]
INVESTOR_TYPE_WEIGHTS = [0.42, 0.10, 0.10, 0.08, 0.04, 0.14, 0.06, 0.06]

STAGE_FOCUS = ["Pre-Seed", "Seed", "Early", "Growth", "Late"]
GEO_FOCUS = ["North America", "Europe", "Asia", "MENA", "LatAm", "Global"]

# --- Exit (data_model 1.4) ---
EXIT_TYPES = ["acquisition", "ipo", "secondary_sale", "write_off"]
EXIT_TYPE_WEIGHTS = [0.55, 0.12, 0.18, 0.15]

# --- Internal deal pipeline (data_model 1.6) ---
DEAL_STAGES = ["sourcing", "screening", "due_diligence", "ic_review", "closing", "closed_won", "closed_lost", "passed"]
IC_OUTCOMES = ["approved", "rejected", "deferred"]

# --- Documents (data_model 1.7) ---
DOCUMENT_TYPES = ["ic_memo", "dd_report", "news_article", "transcript", "vendor_report", "analyst_note"]
DOCUMENT_TYPE_WEIGHTS = [0.18, 0.15, 0.30, 0.10, 0.12, 0.15]
SENSITIVITY_LABELS = ["Public", "Internal", "Confidential", "Highly Confidential"]

COUNTRIES = [
    "United States", "United Kingdom", "Germany", "France", "Netherlands",
    "Sweden", "India", "Singapore", "Canada", "Israel", "Australia",
]
COUNTRY_WEIGHTS = [0.46, 0.11, 0.08, 0.05, 0.04, 0.03, 0.06, 0.05, 0.05, 0.04, 0.03]

# --- Sources ---
SOURCE_DEALROOM = "dealroom"
SOURCE_CAPITALIQ = "capitaliq"
SOURCE_INTERNAL = "internal"
EXTERNAL_SOURCES = [SOURCE_DEALROOM, SOURCE_CAPITALIQ]

VENDOR_ID_PREFIX = {
    SOURCE_DEALROOM: "DR",
    SOURCE_CAPITALIQ: "CIQ",
    SOURCE_INTERNAL: "INT",
}


@dataclass(frozen=True)
class SourceProfile:
    """Per-source behaviour controlling coverage and conflict injection."""
    name: str
    coverage: float                 # P(this source covers a given canonical company)
    announce_lag_mean: float        # mean days between true close and reported announcement
    announce_lag_std: float
    valuation_disclosure: float     # P(valuation fields populated)
    amount_noise_p: float           # P(amount_raised deviates from truth)
    amount_noise_range: tuple       # multiplicative deviation range when noisy
    lead_alter_p: float             # P(lead investor set altered)
    participation_disclosure: float # P(investment participation_amount populated)
    edge_drop_p: float              # P(an investor-round edge missing in this source)


DEALROOM_PROFILE = SourceProfile(
    name=SOURCE_DEALROOM,
    coverage=0.88,
    announce_lag_mean=18.0, announce_lag_std=14.0,
    valuation_disclosure=0.55,
    amount_noise_p=0.15, amount_noise_range=(0.70, 1.30),
    lead_alter_p=0.06,
    participation_disclosure=0.32,
    edge_drop_p=0.10,
)
CAPITALIQ_PROFILE = SourceProfile(
    name=SOURCE_CAPITALIQ,
    coverage=0.82,
    announce_lag_mean=44.0, announce_lag_std=20.0,
    valuation_disclosure=0.72,
    amount_noise_p=0.10, amount_noise_range=(0.82, 1.18),
    lead_alter_p=0.05,
    participation_disclosure=0.40,
    edge_drop_p=0.08,
)
SOURCE_PROFILES = {SOURCE_DEALROOM: DEALROOM_PROFILE, SOURCE_CAPITALIQ: CAPITALIQ_PROFILE}

# Reconciliation tolerances (used by validation to label emergent conflicts;
# WS2 02_reconciliation.py will apply its own, these are for generator self-check)
AMOUNT_DISAGREE_TOLERANCE = 0.05    # >5% relative difference = value_disagreement
ANNOUNCE_DISAGREE_DAYS = 30         # >30 days apart = temporal_disagreement
