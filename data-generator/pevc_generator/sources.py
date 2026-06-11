"""Project canonical ground truth into per-source landing feeds.

Each external source (dealroom, capitaliq) sees a coverage subset and reports
attributes with source-specific bias, producing emergent conflicts:
  - existence_disagreement: entity covered by one source, not the other
  - value_disagreement:      amount_raised / lead set differs across sources
  - temporal_disagreement:   announced_date differs (announce lag varies by source)

Source rows carry vendor IDs (not canonical IDs). The canonical<->vendor mapping
is emitted separately (vendor_id_mapping) per architecture.md §4.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from . import reference as R


def _vendor_id(source: str, entity_short: str, n: int) -> str:
    return f"{R.VENDOR_ID_PREFIX[source]}-{entity_short}-{n:06d}"


def project_sources(canonical: dict, rng: np.random.Generator) -> dict:
    """Returns dict: {source_name: {entity: [rows]}} plus 'vendor_id_mapping'."""
    companies = canonical["companies"]
    investors = canonical["investors"]
    rounds = canonical["funding_rounds"]
    investments = canonical["investments"]

    # Decide coverage per source for each company
    coverage = {}  # company_id -> set(sources)
    for co in companies:
        covered = set()
        for src, prof in R.SOURCE_PROFILES.items():
            if rng.random() < prof.coverage:
                covered.add(src)
        # guarantee at least one source covers each company
        if not covered:
            covered.add(R.SOURCE_DEALROOM)
        coverage[co["company_id"]] = covered

    mapping_rows = []
    feeds = {src: {"companies": [], "funding_rounds": [], "investors": [], "investments": []}
             for src in R.EXTERNAL_SOURCES}

    # counters for vendor ids
    ctr = {src: {"C": 0, "R": 0, "I": 0, "INV": 0} for src in R.EXTERNAL_SOURCES}

    # --- Companies ---
    for co in companies:
        for src in coverage[co["company_id"]]:
            ctr[src]["C"] += 1
            vid = _vendor_id(src, "CO", ctr[src]["C"])
            mapping_rows.append({"canonical_id": co["company_id"], "entity_type": "company",
                                 "source_system": src, "vendor_id": vid})
            # source may report a name variant (legal vs trade name)
            name = co["legal_name"]
            if rng.random() < 0.10:
                name = name.replace(" Inc", "").replace(" Co", "").strip() + (" Inc." if rng.random() < 0.5 else "")
            # source may disagree on a sector tag
            tags = list(co["sector_taxonomy"])
            if rng.random() < 0.15 and len(R.SECTOR_GROUPS[co["sector_group"]]) > len(tags):
                extra = [t for t in R.SECTOR_GROUPS[co["sector_group"]] if t not in tags]
                if extra:
                    tags = tags + [str(rng.choice(extra))]
            feeds[src]["companies"].append({
                "vendor_company_id": vid,
                "legal_name": name,
                "sector_taxonomy": tags,
                "founded_date": co["founded_date"],
                "country": co["headquarters"]["country"],
                "description": co["description"],
            })

    # All investors appear in both sources (lighter conflict on slow-drift attrs)
    inv_vendor = {src: {} for src in R.EXTERNAL_SOURCES}
    for iv in investors:
        for src in R.EXTERNAL_SOURCES:
            ctr[src]["I"] += 1
            vid = _vendor_id(src, "INVR", ctr[src]["I"])
            inv_vendor[src][iv["investor_id"]] = vid
            mapping_rows.append({"canonical_id": iv["investor_id"], "entity_type": "investor",
                                 "source_system": src, "vendor_id": vid})
            fund_size = iv["fund_size"]
            if fund_size is not None and rng.random() < 0.15:
                fund_size = round(fund_size * float(rng.uniform(0.80, 1.20)), 1)  # value disagreement
            sector_focus = list(iv["sector_focus"])
            if rng.random() < 0.12 and len(sector_focus) > 1:
                sector_focus = sector_focus[:-1]  # one source narrower
            feeds[src]["investors"].append({
                "vendor_investor_id": vid,
                "investor_type": iv["investor_type"],
                "legal_name": iv["legal_name"],
                "vintage_year": iv["vintage_year"],
                "fund_size": fund_size,
                "geographic_focus": iv["geographic_focus"],
                "sector_focus": sector_focus,
                "stage_focus": iv["stage_focus"],
            })

    # --- Rounds ---
    round_vendor = {src: {} for src in R.EXTERNAL_SOURCES}
    for rd in rounds:
        # a round is visible to a source only if that source covers the company
        co_sources = coverage[rd["company_id"]]
        true_close = date.fromisoformat(rd["true_close_date"])
        for src in co_sources:
            prof = R.SOURCE_PROFILES[src]
            ctr[src]["R"] += 1
            vid = _vendor_id(src, "RND", ctr[src]["R"])
            round_vendor[src][rd["round_id"]] = vid
            mapping_rows.append({"canonical_id": rd["round_id"], "entity_type": "funding_round",
                                 "source_system": src, "vendor_id": vid})
            # temporal: announced = close + source lag
            lag = max(0, int(rng.normal(prof.announce_lag_mean, prof.announce_lag_std)))
            announced = (true_close + timedelta(days=lag)).isoformat()
            # value: amount noise
            amount = rd["amount_raised"]
            if rng.random() < prof.amount_noise_p:
                amount = round(amount * float(rng.uniform(*prof.amount_noise_range)), 2)
            # valuation disclosure
            if rng.random() < prof.valuation_disclosure:
                pre, post = rd["pre_money_valuation"], rd["post_money_valuation"]
            else:
                pre, post = None, None
            # lead alteration
            lead = list(rd["lead_investor_ids"])
            if rng.random() < prof.lead_alter_p:
                lead = []  # source fails to identify lead
            lead_vendor = [inv_vendor[src].get(x) for x in lead if inv_vendor[src].get(x)]
            feeds[src]["funding_rounds"].append({
                "vendor_round_id": vid,
                "vendor_company_id": _company_vendor(mapping_rows, rd["company_id"], src),
                "round_type": rd["round_type"],
                "announced_date": announced,
                "amount_raised": amount,
                "currency": rd["currency"],
                "pre_money_valuation": pre,
                "post_money_valuation": post,
                "instrument_type": rd["instrument_type"],
                "lead_investor_vendor_ids": lead_vendor,
            })

    # --- Investments ---
    for inv in investments:
        co_sources = coverage[inv["company_id"]]
        for src in co_sources:
            prof = R.SOURCE_PROFILES[src]
            if rng.random() < prof.edge_drop_p:
                continue  # existence disagreement at the edge level
            ctr[src]["INV"] += 1
            vid = _vendor_id(src, "INVT", ctr[src]["INV"])
            mapping_rows.append({"canonical_id": inv["investment_id"], "entity_type": "investment",
                                 "source_system": src, "vendor_id": vid})
            part = inv["participation_amount"] if rng.random() < prof.participation_disclosure else None
            is_lead = inv["is_lead"]
            if rng.random() < 0.08:
                is_lead = not is_lead  # disagreement on lead flag
            feeds[src]["investments"].append({
                "vendor_investment_id": vid,
                "vendor_investor_id": inv_vendor[src].get(inv["investor_id"]),
                "vendor_round_id": round_vendor[src].get(inv["round_id"]),
                "vendor_company_id": _company_vendor(mapping_rows, inv["company_id"], src),
                "participation_amount": part,
                "is_lead": is_lead,
                "board_seat_taken": inv["board_seat_taken"],
                "exit_date": inv["exit_date"],
                "exit_type": inv["exit_type"],
                "realised_return_multiple": inv["realised_return_multiple"],
            })

    feeds["vendor_id_mapping"] = mapping_rows
    return feeds


# Small helper: find a company's vendor id for a source from mapping rows.
# Mapping is append-only and small per company; build a cache lazily.
_company_vendor_cache: dict = {}


def _company_vendor(mapping_rows, canonical_company_id, src):
    key = (canonical_company_id, src)
    if key in _company_vendor_cache:
        return _company_vendor_cache[key]
    # scan from the end (company mappings appended first, so this stays correct)
    for row in mapping_rows:
        if (row["entity_type"] == "company" and row["canonical_id"] == canonical_company_id
                and row["source_system"] == src):
            _company_vendor_cache[key] = row["vendor_id"]
            return row["vendor_id"]
    return None
