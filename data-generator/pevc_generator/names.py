"""Curated name generation for companies, investors, and people.

Deliberately not faker: faker's generic output was a flagged realism weakness.
These banks produce plausible private-market entity names.
"""

from __future__ import annotations

import numpy as np

# --- Company name components ---
_CO_PREFIX = [
    "North", "Bright", "Quanta", "Veridian", "Helio", "Astra", "Cobalt", "Verde",
    "Lumen", "Strata", "Nimbus", "Orbital", "Pioneer", "Vertex", "Cinder", "Polar",
    "Cascade", "Summit", "Atlas", "Meridian", "Ember", "Halcyon", "Onyx", "Lattice",
    "Tessera", "Aurora", "Beacon", "Cardinal", "Drift", "Echo", "Fathom", "Granite",
]
_CO_ROOT = [
    "wave", "flow", "core", "grid", "loop", "shift", "scale", "forge", "stack",
    "bridge", "field", "stone", "spark", "byte", "node", "path", "link", "pulse",
    "labs", "works", "logic", "matter", "form", "sense", "bound", "craft",
]
_CO_SUFFIX_BY_SECTOR = {
    "Information Technology": ["AI", "Cloud", "Systems", "Software", "Compute", "Data", "Networks"],
    "Healthcare": ["Bio", "Health", "Therapeutics", "Dx", "Medical", "Genomics", "Care"],
    "Financials": ["Capital", "Pay", "Lending", "Credit", "Finance", "Markets"],
    "Consumer": ["Brands", "Goods", "Retail", "Commerce", "Co"],
    "Industrials": ["Robotics", "Industries", "Logistics", "Automation", "Materials"],
    "Energy": ["Energy", "Power", "Grid", "Renewables"],
    "Climate": ["Climate", "Carbon", "Renew", "Green"],
    "Mobility": ["Mobility", "Motors", "Drive", "Transit"],
}

# --- Investor (fund/firm) name components ---
_INV_ROOT = [
    "Northwind", "Meridian", "Atlas Bridge", "Helios", "Korbel", "Stonepath",
    "Verdant", "Westgate", "Quill & Stone", "Ironside", "Lighthouse", "Cobalt Lane",
    "Sequoia Ridge", "Benchmark Hollow", "Founders Reach", "Greylock Hill",
    "Accel Point", "Index Cove", "Lightspeed Bay", "Bessemer Row", "Insight Vale",
    "Tiger Brook", "Coatue Park", "General Field", "Andreessen Court",
]
_INV_SUFFIX_BY_TYPE = {
    "vc_fund": ["Ventures", "Capital", "Partners", "VC"],
    "pe_fund": ["Capital Partners", "Equity Partners", "Private Equity", "Capital"],
    "corporate_vc": ["Ventures", "Innovation Fund", "Strategic Capital"],
    "family_office": ["Family Office", "Holdings", "Family Capital"],
    "sovereign_fund": ["Investment Authority", "Sovereign Fund", "Holdings"],
    "angel": [""],  # handled as person-style for angels
    "accelerator": ["Accelerator", "Labs", "Studio"],
    "strategic": ["Holdings", "Group", "Corporation"],
}

# --- People name components ---
_FIRST = [
    "Aarav", "Mia", "Liam", "Sofia", "Noah", "Aisha", "Lucas", "Yuki", "Ethan",
    "Priya", "Mateo", "Lena", "Omar", "Chloe", "Hiro", "Nadia", "Felix", "Zara",
    "Ravi", "Elena", "Sven", "Amara", "Kenji", "Ingrid", "Tomas", "Leila", "Arjun",
    "Clara", "Mohammed", "Greta", "Diego", "Hana", "Viktor", "Sara", "Niam", "Olga",
]
_LAST = [
    "Reddy", "Larsson", "Okafor", "Tanaka", "Schmidt", "Moreau", "Kapoor", "Rossi",
    "Andersen", "Haddad", "Novak", "Singh", "Bauer", "Costa", "Yamamoto", " Feldman".strip(),
    "Petrov", "Nair", "Lindqvist", "Mensah", "Dubois", "Kowalski", "Iyer", "Berg",
    "Cohen", "Mwangi", "Park", "Vasquez", "Nakamura", "Olsen", "Khan", "Romano",
]


def make_company_name(sector_group: str, rng: np.random.Generator) -> str:
    suffixes = _CO_SUFFIX_BY_SECTOR.get(sector_group, ["Co"])
    style = rng.random()
    if style < 0.5:
        return f"{rng.choice(_CO_PREFIX)}{rng.choice(_CO_ROOT)} {rng.choice(suffixes)}".strip()
    elif style < 0.8:
        return f"{rng.choice(_CO_PREFIX)} {rng.choice(suffixes)}".strip()
    else:
        return f"{rng.choice(_CO_PREFIX)}{rng.choice(_CO_ROOT)}".strip().capitalize()


def make_investor_name(investor_type: str, rng: np.random.Generator) -> str:
    if investor_type == "angel":
        return make_person_name(rng)
    root = rng.choice(_INV_ROOT)
    suffix = rng.choice(_INV_SUFFIX_BY_TYPE.get(investor_type, ["Capital"]))
    return f"{root} {suffix}".strip()


def make_person_name(rng: np.random.Generator) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
