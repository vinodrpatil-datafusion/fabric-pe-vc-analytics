"""Canonical ground-truth generation.

Produces the 'real world' for the five entities that originate from external
sources: companies, investors, funding_rounds, investments, people. This oracle
is later projected into per-source feeds (sources.py) with controlled conflicts,
and emitted to reference/ for reconciliation scoring (it is NOT a landing feed).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from . import reference as R
from .names import make_company_name, make_investor_name, make_person_name
from .scale import ScaleProfile

TODAY = date(2026, 6, 1)

# Round/fund size constants below (stage_scale, fund_size lognormal params) are
# calibrated in $ millions for readability — this converts generated amounts to
# actual currency units before they're written out, matching data_model.md's
# "amount_raised: In `currency`" contract (raw units, not millions).
MILLION = 1_000_000


def _rand_date(rng, start: date, end: date) -> date:
    span = (end - start).days
    if span <= 0:
        return start
    return start + timedelta(days=int(rng.integers(0, span)))


def _weighted(rng, items, weights):
    return items[int(rng.choice(len(items), p=weights))]


def generate_canonical(profile: ScaleProfile, rng: np.random.Generator) -> dict:
    companies = _gen_companies(profile, rng)
    investors = _gen_investors(profile, rng)
    rounds, investments = _gen_rounds_and_investments(profile, companies, investors, rng)
    people = _gen_people(profile, companies, investors, rng)
    return {
        "companies": companies,
        "investors": investors,
        "funding_rounds": rounds,
        "investments": investments,
        "people": people,
    }


def _gen_companies(profile, rng) -> list[dict]:
    out = []
    for i in range(1, profile.n_companies + 1):
        group = _weighted(rng, R.SECTOR_GROUP_NAMES, R.SECTOR_GROUP_WEIGHTS)
        tags = list(rng.choice(R.SECTOR_GROUPS[group],
                               size=int(rng.integers(1, 3)), replace=False))
        country = _weighted(rng, R.COUNTRIES, R.COUNTRY_WEIGHTS)
        founded = int(rng.integers(2005, 2024))
        name = make_company_name(group, rng)
        # name_history: ~20% had a prior name
        name_history = []
        if rng.random() < 0.20:
            prior = make_company_name(group, rng)
            change_year = min(2025, founded + int(rng.integers(1, 6)))
            name_history = [
                {"name": prior, "from": f"{founded}-01-01", "to": f"{change_year}-01-01"},
                {"name": name, "from": f"{change_year}-01-01", "to": None},
            ]
        out.append({
            "company_id": f"C-{i:05d}",
            "legal_name": name,
            "name_history": name_history,
            "sector_group": group,
            "sector_taxonomy": tags,
            "founded_date": f"{founded}-{int(rng.integers(1,13)):02d}-01",
            "headquarters": {
                "country": country,
                "region": None,
                "city": None,
            },
            "description": f"{name} operates in {tags[0]} within the {group} sector.",
            # hidden lifecycle for exit modelling (not a landing column)
            "_founded_year": founded,
        })
    return out


def _gen_investors(profile, rng) -> list[dict]:
    out = []
    for i in range(1, profile.n_investors + 1):
        itype = _weighted(rng, R.INVESTOR_TYPES, R.INVESTOR_TYPE_WEIGHTS)
        is_fund = itype in ("vc_fund", "pe_fund", "corporate_vc", "sovereign_fund")
        vintage = int(rng.integers(2008, 2024)) if is_fund else None
        if itype == "vc_fund":
            fund_size = round(float(rng.lognormal(5.6, 0.8)) * MILLION, 1)   # ~$270M median
        elif itype == "pe_fund":
            fund_size = round(float(rng.lognormal(7.2, 0.7)) * MILLION, 1)   # ~$1.3B median
        elif itype in ("corporate_vc", "sovereign_fund"):
            fund_size = round(float(rng.lognormal(6.5, 0.9)) * MILLION, 1)
        else:
            fund_size = None
        out.append({
            "investor_id": f"I-{i:05d}",
            "investor_type": itype,
            "legal_name": make_investor_name(itype, rng),
            "fund_manager_id": None,
            "vintage_year": vintage,
            "fund_size": fund_size,
            "geographic_focus": list(rng.choice(R.GEO_FOCUS, size=int(rng.integers(1, 3)), replace=False)),
            "sector_focus": list(rng.choice(R.SECTOR_GROUP_NAMES, size=int(rng.integers(1, 4)), replace=False)),
            "stage_focus": list(rng.choice(R.STAGE_FOCUS, size=int(rng.integers(1, 3)), replace=False)),
        })
    return out


def _next_round_type(prev: str | None, rng) -> str:
    if prev is None:
        items = list(R.FIRST_ROUND_WEIGHTS.keys())
        weights = list(R.FIRST_ROUND_WEIGHTS.values())
        return items[int(rng.choice(len(items), p=weights))]
    progression = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E"]
    if prev in progression:
        idx = progression.index(prev)
        if rng.random() < 0.15:
            return "Bridge"
        return progression[min(idx + 1, len(progression) - 1)]
    return "Growth"


def _gen_rounds_and_investments(profile, companies, investors, rng):
    rounds = []
    investments = []
    round_idx = 1
    inv_idx = 1
    investor_ids = [iv["investor_id"] for iv in investors]

    for co in companies:
        n_rounds = int(np.clip(rng.poisson(1.8), 0, profile.max_rounds_per_company))
        if n_rounds == 0:
            continue
        # First round no earlier than founding
        cur = date(co["_founded_year"], 1, 1) + timedelta(days=int(rng.integers(60, 720)))
        prev_type = None
        # decide company exit
        exits = rng.random() < 0.30
        exit_type = _weighted(rng, R.EXIT_TYPES, R.EXIT_TYPE_WEIGHTS) if exits else None
        exit_date = _rand_date(rng, cur + timedelta(days=900), TODAY) if exits else None

        for _ in range(n_rounds):
            if cur >= TODAY:
                break
            rtype = _next_round_type(prev_type, rng)
            prev_type = rtype
            currency = _weighted(rng, R.CURRENCIES, R.CURRENCY_WEIGHTS)
            # amount scales with round stage
            stage_scale = {"Pre-Seed": 1.0, "Seed": 2.5, "Series A": 8.0, "Series B": 20.0,
                           "Series C": 45.0, "Series D": 90.0, "Series E": 150.0,
                           "Bridge": 4.0, "Growth": 120.0}.get(rtype, 10.0)
            amount = round(float(rng.lognormal(np.log(stage_scale), 0.5)) * MILLION, 2)
            post = round(amount / float(rng.uniform(0.10, 0.30)), 2)
            pre = round(post - amount, 2)
            instrument = _weighted(rng, R.INSTRUMENT_TYPES, R.INSTRUMENT_WEIGHTS)

            # investors in this round
            n_inv = int(np.clip(rng.poisson(2.5), 1, 6))
            chosen = list(rng.choice(investor_ids, size=min(n_inv, len(investor_ids)), replace=False))
            lead = chosen[0]

            round_id = f"R-{round_idx:06d}"
            true_close = cur
            rounds.append({
                "round_id": round_id,
                "company_id": co["company_id"],
                "round_type": rtype,
                "true_close_date": true_close.isoformat(),   # oracle truth
                "amount_raised": amount,
                "currency": currency,
                "pre_money_valuation": pre,
                "post_money_valuation": post,
                "instrument_type": instrument,
                "lead_investor_ids": [lead],
            })
            round_idx += 1

            for inv_id in chosen:
                is_lead = inv_id == lead
                exited = exits and exit_date is not None
                ret_mult = None
                if exited:
                    if exit_type == "write_off":
                        ret_mult = 0.0
                    else:
                        ret_mult = round(float(np.clip(rng.lognormal(0.6, 0.6), 0.2, 15.0)), 2)
                investments.append({
                    "investment_id": f"INV-{inv_idx:07d}",
                    "investor_id": inv_id,
                    "round_id": round_id,
                    "company_id": co["company_id"],
                    "participation_amount": round(amount * float(rng.uniform(0.1, 0.6)), 2),
                    "is_lead": is_lead,
                    "board_seat_taken": bool(is_lead and rng.random() < 0.7),
                    "effective_date": true_close.isoformat(),
                    "exit_date": exit_date.isoformat() if exited else None,
                    "exit_type": exit_type if exited else None,
                    "realised_return_multiple": ret_mult,
                })
                inv_idx += 1

            # next round 9-30 months later
            cur = cur + timedelta(days=int(rng.integers(270, 900)))

    return rounds, investments


def _gen_people(profile, companies, investors, rng) -> list[dict]:
    out = []
    company_ids = [c["company_id"] for c in companies]
    for i in range(1, profile.n_people + 1):
        n_current = int(np.clip(rng.poisson(1.1), 0, 3))
        n_hist = int(np.clip(rng.poisson(1.3), 0, 4))
        current = []
        for _ in range(n_current):
            current.append({
                "company_id": str(rng.choice(company_ids)),
                "role": _weighted(rng, ["Founder", "CEO", "CTO", "Board Member", "Partner", "VP"],
                                  [0.18, 0.15, 0.12, 0.20, 0.20, 0.15]),
                "start_date": _rand_date(rng, date(2012, 1, 1), TODAY).isoformat(),
            })
        historical = []
        for _ in range(n_hist):
            s = _rand_date(rng, date(2005, 1, 1), date(2020, 1, 1))
            e = _rand_date(rng, s + timedelta(days=400), date(2023, 1, 1))
            historical.append({
                "company_id": str(rng.choice(company_ids)),
                "role": _weighted(rng, ["Engineer", "Founder", "Exec", "Advisor"], [0.4, 0.2, 0.25, 0.15]),
                "start_date": s.isoformat(),
                "end_date": e.isoformat(),
                "reason": _weighted(rng, ["acquired", "left", "ipo", "shutdown"], [0.3, 0.4, 0.1, 0.2]),
            })
        out.append({
            "person_id": f"P-{i:05d}",
            "name": make_person_name(rng),
            "current_affiliations": current,
            "historical_affiliations": historical,
            "education": list(rng.choice(
                ["MIT", "Stanford", "ETH Zurich", "IIT Bombay", "Oxford", "TU Munich", "INSEAD", "Berkeley"],
                size=int(rng.integers(1, 3)), replace=False)),
            "notable_prior_companies": [],
        })
    return out
