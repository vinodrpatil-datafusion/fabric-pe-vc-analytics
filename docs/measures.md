# Measure contract — `pevc-semantic-model`

This document is the **business contract** for the measures in the DirectLake semantic
model: what each number means from the LP's seat, at what grain it is valid, and which
caveats travel with it. The **source of truth for implementation** is the TMDL under
[`fabric/pevc-dev/pevc-semantic-model.SemanticModel/`](../fabric/pevc-dev/pevc-semantic-model.SemanticModel/definition/tables/gold_fact_investment.tmdl);
if this document and the TMDL disagree, the TMDL wins and this document has a bug.

Decision rationale is **not** restated here — see
[`design_decisions.md`](design_decisions.md) DD-15 (Gold grain, NAV-proxy convention)
and DD-16 (IRR-proxy method). This page is definition and usage, not justification.

All measures live on `gold_fact_investment` (grain: one row per `investment_id`,
current version only — DD-15) and roll up through `dim_company`, `dim_investor`,
and `dim_date`.

---

## Vantage point: an LP lens, not an LP position model

The report is framed from the LP's seat, but the model contains **no LP entity** —
no commitments, capital calls, distributions, or LP ownership shares
([`data_model.md`](data_model.md) defers LP relationships as a future extension).
The fact grain is **fund → company** deployments. The measures therefore read the
full investment universe as a **single consolidated portfolio** — the implicit
viewer is an allocator with exposure to every fund in scope (a fund-of-funds view),
not one LP's pro-rata position. "Invested capital" throughout this document means
the funds' deployed capital, not any LP's paid-in capital. Adding the
commitment-and-cash-flow layer is the same extension that would unlock DPI, TVPI,
and a true money-weighted IRR (see the DPI section below).

---

## Naming note: "5 core measures" vs. 7 defined measures

The README describes "5 core measures (MOIC, IRR proxy, NAV proxy, sector
concentration, vintage performance)". Precisely:

- **Vintage performance is not a standalone measure.** It is the core measures
  (MOIC, IRR proxy) placed in the filter context of `dim_investor[vintage_year]` —
  a slicing pattern, not a DAX object.
- The model defines **7 measures**: the 4 headline LP measures below, plus 2
  supporting measures (`Cost-Weighted Avg Years Held`, `Cumulative NAV (proxy)`)
  and `Sector Concentration %`.

---

## Headline LP measures

### Total Invested

- **LP meaning:** capital actually deployed into portfolio companies within the
  current filter context. Deployed, not committed — this dataset does not model
  commitments or capital calls.
- **Definition:** `SUM(gold_fact_investment[participation_amount])`
- **Valid grain:** additive across all dimensions; safe at any slice.
- **Caveats:** cost basis only. No currency conversion is modelled (single-currency
  synthetic dataset).

### NAV (proxy)

- **LP meaning:** estimated current worth of the portfolio in filter context —
  realised proceeds for exited positions plus held positions.
- **Definition:** per investment, `participation_amount × realised_return_multiple`
  when `is_realized`, else `participation_amount`; summed (`SUMX`).
- **Valid grain:** additive; safe at any slice.
- **Caveats (mandatory, DD-15):** this is a **proxy, not a NAV**. The dataset carries
  no periodic fair-value marks, so unrealised positions are held at cost (1.0×).
  Realised positions use their final exit multiple. Do not present as an audited or
  GP-reported NAV. Note the same scepticism applies to any real GP-supplied NAV that
  is not independently marked — the caveat is a feature of honest LP reporting, not
  just of synthetic data.

### MOIC

- **LP meaning:** Multiple on Invested Capital — how many multiples of deployed
  capital the portfolio (in filter context) is worth, realised + unrealised.
- **Definition:** `DIVIDE([NAV (proxy)], [Total Invested])` — the **pooled** MOIC
  pattern (DD-16): value and cost are summed first, then divided once. Per-investment
  multiples are never simple-averaged, which would over-weight small positions.
- **Valid grain:** any slice (portfolio, fund, vintage, sector). Non-additive —
  a MOIC of sub-slices cannot be summed or averaged to get the parent MOIC.
- **Caveats:** inherits the NAV-proxy convention — unrealised positions contribute
  1.0×, so portfolio MOIC is **biased toward 1.0× until exits occur**. MOIC ignores
  time entirely; read alongside IRR (proxy).

### IRR (proxy)

- **LP meaning:** time-adjusted annualised return — corrects MOIC's blindness to
  holding period.
- **Definition (DD-16):** `pooled_MOIC ^ (1 / cost_weighted_avg_years_held) − 1`,
  annualisation applied **once** at the sliced grain, never averaged up from
  per-investment IRRs.
- **Valid grain:** any slice, with the same non-additivity as MOIC.
- **Caveats (mandatory, DD-16):** assumes a single lump-sum flow in and one flow
  out — no interim capital calls or partial distributions are modelled.
  **Directionally correct for ranking** (better/worse vintage, sector, fund);
  **not** an audited money-weighted fund IRR. XIRR over synthesised cash-flow events
  was explicitly rejected (DD-16) as false precision.

### Sector Concentration %

- **LP meaning:** the LP's risk question — what share of the deployed capital sits
  in each sector. Not a GP allocation view. (Per the vantage-point note above:
  "deployed capital" is the consolidated fund universe, not an LP's pro-rata share.)
- **Definition:** `DIVIDE([Total Invested], CALCULATE([Total Invested],
  ALL(gold_dim_company[sector_group])))`
- **Valid grain:** designed for slicing by `dim_company[sector_group]` (the derived
  single-valued sector attribute — see DD-15 on the taxonomy-lookup shortcut).
  Percentages sum to 100% across sectors within any outer filter context.
- **Caveats:** denominators respect outer filters except `sector_group` itself.
  `sector_taxonomy` (the multi-valued array) is not bridged; companies are counted
  under one `sector_group` only.

---

## Supporting measures

### Cost-Weighted Avg Years Held

- **Purpose:** the holding-period input to the IRR proxy. Weighted by
  `participation_amount` so large positions dominate, per DD-16.
- **Definition:** cost-weighted `DATEDIFF(effective_date, exit_date or TODAY())`
  in years, divided by `[Total Invested]`.
- **Caveats:** uses `TODAY()` for open positions — the value **drifts daily** for
  unrealised holdings, and therefore so does IRR (proxy). Expected behaviour, worth
  knowing when screenshots don't reproduce.

### Cumulative NAV (proxy)

- **Purpose:** running NAV-proxy over the date axis for trend visuals.
- **Definition:** `[NAV (proxy)]` under `FILTER(ALL(gold_dim_date),
  date <= MAX(date))`.
- **Caveats:** inherits all NAV-proxy caveats; meaningful only with `dim_date` on
  an axis.

---

## Vintage performance (slicing pattern, not a measure)

Place MOIC and IRR (proxy) against `dim_investor[vintage_year]`. This is the standard
LP comparison — funds are judged within their vintage cohort because macro conditions
(rates, entry valuations, exit windows) dominate outcomes. No dedicated DAX object
exists or is needed; the pooled-MOIC and single-annualisation conventions above make
the measures valid at vintage grain by construction.

---

## Deliberately absent: DPI (Distributions to Paid-In)

DPI — cash actually returned ÷ cash invested, the "show me the money" metric LPs pair
with MOIC ("MOIC is paper, DPI is real") — is **not** in this model, deliberately:

- The conformed layer models exits as a terminal `realised_return_multiple`, not as
  dated distribution *events*. A DPI without distribution timing would collapse into
  the realised share of the NAV proxy — a duplicate number wearing a more credible name.
- Synthesising distribution timing was rejected for the same reason DD-16 rejected
  XIRR: manufactured precision is worse than a labelled proxy.

**When you'd add it:** if the synthetic generator is extended to emit dated
distribution/capital-call events, DPI (and RVPI, TVPI, and a true XIRR) become
computable honestly. This is the same commitment-and-cash-flow layer named in the
vantage-point note above — one extension, two payoffs: true LP-position attribution
and the realised-return metric family. It would warrant its own design decision.

---

*This contract covers the semantic model as of DD-16 (2026-07-14). New measures are
appended here in the same PR that adds them to the model.*
