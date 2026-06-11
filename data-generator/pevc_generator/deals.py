"""Deals, valuations (quarterly NAV marks), and cashflows.

Each company gets a coherent narrative:
  - Primary investment deal at entry_date (with ownership and valuation)
  - Optional follow-on deals during holding period
  - Quarterly NAV marks producing a plausible J-curve / return path
  - Capital calls and distributions feeding into LP-level cashflow rollups
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .lineage import LineageContext, attach_lineage
from .reference import VALUATION_METHOD_WEIGHTS, VALUATION_METHODS

CURRENT_DATE = date(2026, 5, 13)


def _quarter_ends_between(start: date, end: date) -> list[date]:
    """Return list of quarter-end dates strictly after `start` and up to `end`."""
    out = []
    y, q = start.year, (start.month - 1) // 3 + 1
    while True:
        q += 1
        if q > 4:
            q = 1
            y += 1
        # Quarter end date
        month_end = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[q]
        qe = date(y, month_end[0], month_end[1])
        if qe > end:
            break
        out.append(qe)
    return out


def generate_deals_valuations_cashflows(
    funds_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    rng: np.random.Generator,
    ctx: LineageContext,
):
    """Returns three DataFrames: deals, valuations, cashflows (fund-level).

    Cashflows here are fund-level (capital calls and distributions per fund per date).
    LP-level cashflow attribution is derived later in the Silver/Gold layers
    using LP commitment ratios — that's a transformation concern, not a generation one.
    """
    deal_rows = []
    val_rows = []
    cf_rows = []
    deal_idx = 1
    val_idx = 1
    cf_idx = 1

    fund_lookup = funds_df.set_index("fund_id").to_dict("index")

    for _, co in companies_df.iterrows():
        fund_id = co["fund_id"]
        fund = fund_lookup[fund_id]
        currency = fund["currency"]

        # ---- Primary investment ----
        # Initial investment size scales with fund committed capital
        # Typical PE deal: 3–10% of fund per company
        invest_share = rng.uniform(0.03, 0.10)
        primary_amount = round(fund["committed_capital_m"] * invest_share, 2)

        ownership_pct = round(float(rng.uniform(15, 85)), 2)
        # Post-money valuation implied by ownership and check size
        post_money = round(primary_amount / (ownership_pct / 100.0), 2)
        pre_money = round(post_money - primary_amount, 2)

        entry_date = co["entry_date"]
        deal_rows.append({
            "deal_id": f"DEAL-{deal_idx:06d}",
            "fund_id": fund_id,
            "company_id": co["company_id"],
            "deal_type": "Primary",
            "deal_date": entry_date,
            "amount_m": primary_amount,
            "ownership_pct": ownership_pct,
            "valuation_pre_money_m": pre_money,
            "valuation_post_money_m": post_money,
            "currency": currency,
        })
        deal_idx += 1

        # Capital call for primary
        cf_rows.append({
            "cashflow_id": f"CF-{cf_idx:07d}",
            "fund_id": fund_id,
            "company_id": co["company_id"],
            "cashflow_date": entry_date,
            "cashflow_type": "Capital Call",
            "amount_m": primary_amount,
            "currency": currency,
        })
        cf_idx += 1

        # ---- Optional follow-on deals ----
        holding_end = co["exit_date"] if co["exit_date"] else CURRENT_DATE
        n_followons = int(rng.poisson(0.8))
        followon_total = 0.0
        for _ in range(n_followons):
            if (holding_end - entry_date).days < 365:
                break
            offset_days = int(rng.integers(365, max(366, (holding_end - entry_date).days)))
            fo_date = entry_date + timedelta(days=offset_days)
            if fo_date >= holding_end:
                continue
            fo_amount = round(primary_amount * float(rng.uniform(0.2, 0.6)), 2)
            followon_total += fo_amount
            deal_rows.append({
                "deal_id": f"DEAL-{deal_idx:06d}",
                "fund_id": fund_id,
                "company_id": co["company_id"],
                "deal_type": "Follow-On",
                "deal_date": fo_date,
                "amount_m": fo_amount,
                "ownership_pct": ownership_pct,  # simplification: ownership held constant
                "valuation_pre_money_m": None,
                "valuation_post_money_m": None,
                "currency": currency,
            })
            deal_idx += 1
            cf_rows.append({
                "cashflow_id": f"CF-{cf_idx:07d}",
                "fund_id": fund_id,
                "company_id": co["company_id"],
                "cashflow_date": fo_date,
                "cashflow_type": "Capital Call",
                "amount_m": fo_amount,
                "currency": currency,
            })
            cf_idx += 1

        total_invested = primary_amount + followon_total

        # ---- Outcome multiple (the return path) ----
        # Skewed log-normal: median ~1.8x, fat tail of winners, write-offs at 0
        if co["status"] == "Written Off":
            final_multiple = 0.0
        elif co["status"] == "Exited":
            # Successful exits: median ~2.5x, with some 5x+ winners
            final_multiple = float(rng.lognormal(0.9, 0.6))
            final_multiple = max(0.5, min(final_multiple, 12.0))
        else:  # Active
            # Mark-to-current — typically 1.0–3.0x but unrealised
            final_multiple = float(rng.lognormal(0.5, 0.5))
            final_multiple = max(0.3, min(final_multiple, 8.0))

        # ---- Quarterly NAV marks from entry to (exit or now) ----
        nav_end = co["exit_date"] if co["exit_date"] else CURRENT_DATE
        quarter_ends = _quarter_ends_between(entry_date, nav_end)
        if not quarter_ends:
            # Very recent investment — at least one mark at next quarter end
            continue

        n_marks = len(quarter_ends)
        # Build a smooth path from 1.0x toward final_multiple, with noise (J-curve in early quarters)
        # Early quarters: dip below 1.0 (J-curve), then climb toward final
        path = np.zeros(n_marks)
        for i in range(n_marks):
            t = (i + 1) / n_marks
            # J-curve: lower in first ~25% of hold then rising
            j_curve = 1.0 - 0.15 * max(0, 0.3 - t) / 0.3
            target = j_curve * (1 - t) + final_multiple * t
            noise = float(rng.normal(0, 0.05))
            path[i] = max(0.0, target + noise)

        # Ensure final mark equals declared outcome (clean exit value)
        path[-1] = final_multiple

        for i, qe in enumerate(quarter_ends):
            fair_value = round(total_invested * path[i], 2)
            method = rng.choice(VALUATION_METHODS, p=VALUATION_METHOD_WEIGHTS)
            val_rows.append({
                "valuation_id": f"VAL-{val_idx:07d}",
                "fund_id": fund_id,
                "company_id": co["company_id"],
                "valuation_date": qe,
                "fair_value_m": fair_value,
                "valuation_method": method,
                "currency": currency,
            })
            val_idx += 1

        # ---- Exit distribution (if exited) ----
        if co["exit_date"] and co["status"] == "Exited":
            exit_proceeds = round(total_invested * final_multiple, 2)
            cf_rows.append({
                "cashflow_id": f"CF-{cf_idx:07d}",
                "fund_id": fund_id,
                "company_id": co["company_id"],
                "cashflow_date": co["exit_date"],
                "cashflow_type": "Distribution",
                "amount_m": exit_proceeds,
                "currency": currency,
            })
            cf_idx += 1
            deal_rows.append({
                "deal_id": f"DEAL-{deal_idx:06d}",
                "fund_id": fund_id,
                "company_id": co["company_id"],
                "deal_type": "Exit",
                "deal_date": co["exit_date"],
                "amount_m": exit_proceeds,
                "ownership_pct": ownership_pct,
                "valuation_pre_money_m": None,
                "valuation_post_money_m": round(exit_proceeds / (ownership_pct / 100.0), 2),
                "currency": currency,
            })
            deal_idx += 1

    deals_df = pd.DataFrame(deal_rows)
    valuations_df = pd.DataFrame(val_rows)
    cashflows_df = pd.DataFrame(cf_rows)

    deals_df = attach_lineage(deals_df, ctx, source_file="deals.parquet")
    valuations_df = attach_lineage(valuations_df, ctx, source_file="valuations.parquet")
    cashflows_df = attach_lineage(cashflows_df, ctx, source_file="cashflows.parquet")

    return deals_df, valuations_df, cashflows_df
