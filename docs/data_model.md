# Data Model — Investment Analytics Domain

This document describes the domain entities, their attributes, relationships, and the modelling rationale. It is the schema-level companion to [`architecture.md`](architecture.md) and [`design_decisions.md`](design_decisions.md).

The model is implemented in the **conformed Lakehouse** as Delta tables. Serving layers (Warehouse views, semantic model, AI retrieval functions) consume this model without redefining it.

---

## 1. Domain entities

Ten core entities. Each is described with purpose, key attributes, temporal pattern, and the rationale behind any non-obvious modelling choice.

### 1.1 Companies

Private and public companies tracked across the platform.

| Attribute | Type | Notes |
|---|---|---|
| `company_id` | string (UUID) | Internal stable identifier. Vendor IDs (DealRoom, Capital IQ) maintained separately in mapping table. |
| `legal_name` | string | Current legal name. |
| `name_history` | array<struct> | Historical names with `from`/`to` dates. |
| `sector_taxonomy` | array<string> | Multi-tag; internal taxonomy mapped to vendor taxonomies via lookup. |
| `founded_date` | date | Effective founding date. |
| `headquarters` | struct | Country, region, city with effective-date tracking. |
| `description` | string | Latest description; embeddings stored in `documents` entity. |
| `effective_date` | date | When this company snapshot became true in the world. |
| `ingestion_date` | timestamp | When this row reached the conformed layer. |
| `source_attribution` | array<string> | Sources that contributed to this row. |
| `reconciliation_status` | string | `clean`, `conflict_resolved`, or `conflict_flagged`. |

**Modelling rationale:** Companies are bitemporal because their attributes (sector tags, headquarters, name) change over time and historical analyses need to reflect the state at the relevant point. Vendor ID mapping is separated so platform identity is not coupled to any one vendor.

### 1.2 Funding rounds

Capital events affecting a company.

| Attribute | Type | Notes |
|---|---|---|
| `round_id` | string (UUID) | |
| `company_id` | string | FK to companies. |
| `round_type` | string | Seed, Series A, B, C, Bridge, etc. |
| `announced_date` | date | When the round was publicly disclosed. |
| `effective_date` | date | When the round actually closed (often earlier than announcement). |
| `ingestion_date` | timestamp | |
| `amount_raised` | decimal | In `currency`. |
| `currency` | string | ISO 4217. |
| `pre_money_valuation` | decimal | Nullable; often undisclosed. |
| `post_money_valuation` | decimal | Nullable. |
| `instrument_type` | string | Equity, convertible note, SAFE, etc. |
| `lead_investor_ids` | array<string> | FKs to investors. |
| `source_attribution` | array<string> | |
| `reconciliation_status` | string | |

**Modelling rationale:** The `announced_date` vs `effective_date` distinction is essential. Investment data is rife with rounds disclosed months after closing. Storing only the announced date leads to historical analyses that misrepresent capital deployment timing.

`pre_money_valuation` and `post_money_valuation` are explicitly nullable. Private market data has sparse valuation disclosure; modelling pretends otherwise at the cost of analyst trust.

### 1.3 Investors

Funds, fund managers, and investing entities.

| Attribute | Type | Notes |
|---|---|---|
| `investor_id` | string (UUID) | |
| `investor_type` | string | `vc_fund`, `pe_fund`, `corporate_vc`, `family_office`, `sovereign_fund`, `angel`, `accelerator`, `strategic` |
| `legal_name` | string | |
| `fund_manager_id` | string | FK to fund managers entity (where applicable). |
| `vintage_year` | int | For funds; null for non-fund investors. |
| `fund_size` | decimal | Where disclosed. |
| `geographic_focus` | array<string> | |
| `sector_focus` | array<string> | |
| `stage_focus` | array<string> | Seed, growth, late-stage, etc. |
| `source_attribution` | array<string> | |

**Modelling rationale:** Investor type is a discriminating field because fund-level entities (vintage year, fund size) and non-fund entities (angels, strategic acquirers) have different attribute sets. Storing them in one table with type-conditional fields is more analytically useful than splitting into separate tables.

### 1.4 Investments

The n-to-n bridge: which investor participated in which round of which company, with deal terms.

| Attribute | Type | Notes |
|---|---|---|
| `investment_id` | string (UUID) | |
| `investor_id` | string | FK to investors. |
| `round_id` | string | FK to funding rounds. |
| `company_id` | string | FK to companies (denormalised for query convenience). |
| `participation_amount` | decimal | Investor's specific contribution. Often undisclosed. |
| `is_lead` | boolean | |
| `board_seat_taken` | boolean | |
| `effective_date` | date | Investment effective date (typically equals round effective date). |
| `exit_date` | date | Nullable; populated on exit. |
| `exit_type` | string | `acquisition`, `ipo`, `secondary_sale`, `write_off`, null while held. |
| `realised_return_multiple` | decimal | Nullable until exit. |

**Modelling rationale:** The investments table is the platform's central analytical asset. Most interesting queries — fund performance, co-investment patterns, sector concentration, vintage analysis — pivot through it. Denormalising `company_id` (already accessible via the round) is a deliberate query-performance trade-off.

Exit tracking is embedded here rather than in a separate exits table because exits are properties of the investment, not events with their own significance independent of the underlying capital deployment.

### 1.5 People

Founders, board members, fund partners, executives.

| Attribute | Type | Notes |
|---|---|---|
| `person_id` | string (UUID) | |
| `name` | string | |
| `current_affiliations` | array<struct> | Company/role/start date for active relationships. |
| `historical_affiliations` | array<struct> | Same shape, plus end_date and reason. |
| `education` | array<struct> | |
| `notable_prior_companies` | array<string> | |
| `source_attribution` | array<string> | |

**Modelling rationale:** Affiliations as nested arrays rather than a separate join table is a Delta-friendly choice — the typical query is "what is this person's history" or "who has worked at company X". Both are well-served by array operations. A separate affiliations table would be more relationally pure but adds join overhead for the dominant query patterns.

People are the connective tissue for graph queries — founder-team overlap, board-member-mediated relationships, partner-portfolio company history.

### 1.6 Deals (internal pipeline)

Internal record of deals under consideration, in progress, or closed by the investing firm consuming the platform.

| Attribute | Type | Notes |
|---|---|---|
| `deal_id` | string (UUID) | |
| `company_id` | string | FK to companies. |
| `stage` | string | `sourcing`, `screening`, `due_diligence`, `ic_review`, `closing`, `closed_won`, `closed_lost`, `passed` |
| `stage_history` | array<struct> | Stage transitions with timestamps. |
| `analyst_owner` | string | |
| `partner_owner` | string | |
| `proposed_check_size` | decimal | |
| `target_round_id` | string | FK to funding rounds when the deal targets a specific round. |
| `ic_date` | date | Scheduled or actual IC review date. |
| `ic_outcome` | string | `approved`, `rejected`, `deferred`, null. |
| `effective_date` | date | |
| `ingestion_date` | timestamp | |

**Modelling rationale:** Internal deals are the integration point between the analytics platform and the firm's investment workflow. The stage history is array-modelled because workflow analysis (time-in-stage, conversion rates, bottleneck identification) depends on it being queryable as a sequence.

This is the most sensitive entity from a security perspective — internal deal pipeline data is the firm's proprietary view of the market. Sensitivity labels and access controls are most restrictive here.

### 1.7 Documents

Unstructured artefacts: memos, transcripts, news articles, vendor reports.

| Attribute | Type | Notes |
|---|---|---|
| `document_id` | string (UUID) | |
| `document_type` | string | `ic_memo`, `dd_report`, `news_article`, `transcript`, `vendor_report`, `analyst_note` |
| `subject_company_ids` | array<string> | Companies this document is about. |
| `subject_deal_ids` | array<string> | Internal deals this document relates to. |
| `author_person_id` | string | Nullable. |
| `created_date` | date | |
| `ingestion_date` | timestamp | |
| `storage_location` | string | OneLake path to the source file. |
| `extracted_text` | string | Full text for retrieval. |
| `embedding_index_id` | string | Pointer to vector index entry. |
| `sensitivity_label` | string | Propagated to retrieval context. |

**Modelling rationale:** Documents are the bridge between structured analytics and unstructured AI workloads. Storing the extracted text in the table (rather than only in vector index) supports keyword and entity search through standard SQL alongside semantic retrieval through the vector index.

Sensitivity labels at the document level propagate into AI retrieval — documents marked confidential cannot leak into responses surfaced to users without confidential access.

### 1.8 Reconciliation log

Cross-cutting audit table.

| Attribute | Type | Notes |
|---|---|---|
| `reconciliation_id` | string (UUID) | |
| `entity_type` | string | `company`, `funding_round`, `investor`, `investment`. |
| `entity_id` | string | |
| `conflict_type` | string | `value_disagreement`, `existence_disagreement`, `temporal_disagreement`. |
| `sources_involved` | array<string> | |
| `conflict_detail` | string | Structured description. |
| `resolution_action` | string | `auto_resolved`, `flagged_for_review`, `manual_resolved`. |
| `resolved_by` | string | User identifier or `system`. |
| `resolved_date` | timestamp | |

**Modelling rationale:** The reconciliation log makes data quality work visible and auditable. When an analyst asks "why does our platform show $50M raised when DealRoom shows $45M", the answer is in this log, not buried in pipeline code.

### 1.9 LP documents

Fund-to-LP communications: quarterly letters, capital call notices, and exit-notice memos. Kept separate from `documents` (§1.7) — different purpose (LP communications, not deal-pipeline records) and a different sensitivity profile (DD-17).

| Attribute | Type | Notes |
|---|---|---|
| `lp_document_id` | string | e.g. `LPD-000001`. |
| `document_type` | string | `quarterly_letter`, `capital_call_notice`, `memo`. |
| `investor_id` | string | FK to investors — the fund authoring/sending it. |
| `effective_date` | date | Quarter-end for letters, call/exit date otherwise. |
| `ingestion_date` | timestamp | |
| `body_text` | string | Templated prose — no LLM generation, no fabricated numeric precision. |

**Modelling rationale:** scoped to fund-type investors only (`investors.vintage_year` populated) — angels, accelerators, and strategics don't raise from LPs, so it wouldn't make sense for them to issue capital calls or LP letters. Generated directly from canonical ground truth (an investment's `participation_amount`, a round's `round_type`, an exit's `realised_return_multiple`), so every fact stated in a document is traceable to a real underlying row, not invented.

### 1.10 LP document manifest

Citation ground truth for `lp_documents` — flattens each document's cross-references into one row per reference, rather than array columns, so Stage E's evaluation harness can score retrieval citations against individual entity IDs across heterogeneous types.

| Attribute | Type | Notes |
|---|---|---|
| `lp_document_id` | string | FK to `lp_documents`. |
| `entity_type` | string | `investor`, `company`, `round`. |
| `entity_id` | string | The referenced entity's natural key. |

---

## 2. Relationship density

The investment domain is graph-shaped. The most analytically valuable queries traverse multiple hops:

**2-hop queries** (common):
- A company's funding history → which investors backed it
- An investor's portfolio → which companies are in it
- A person's affiliations → which companies they're connected to

**3-hop queries** (frequent):
- Co-investment patterns: companies → rounds → other investors in those rounds
- Founder networks: people → prior companies → other people at those companies
- Sector concentration: investors → portfolio companies → sector taxonomy

**4-hop queries** (less frequent, high value):
- Comparable identification: target company → similar companies (by sector, stage) → their investors → other companies those investors back
- Warm intro paths: target company → its people → their network → our portfolio company people

The conformed Delta tables support all of these via SQL CTEs or Spark GraphFrames. A dedicated graph database would optimise the 4-hop pattern further; see DD-07 in `design_decisions.md`.

---

## 3. Temporal patterns by entity

Not every entity needs bitemporal modelling. The pattern applied:

| Entity | Temporal pattern | Rationale |
|---|---|---|
| Companies | Bitemporal | Attributes change over time; historical state matters for backtesting. |
| Funding rounds | Bitemporal | Announcement vs effective date gap is material. |
| Investors | Type 2 SCD on key attributes | Fund-level attributes (sector focus) drift slowly. |
| Investments | Bitemporal | Investment effective date and exit date both matter. |
| People | Type 2 SCD on affiliations | Affiliations are time-bound; rest is mostly stable. |
| Deals (internal) | Single-temporal with stage history | Internal pipeline is forward-only; corrections are rare. |
| Documents | Single-temporal (created_date) | Documents are immutable artefacts. |
| Reconciliation log | Append-only | Audit log; never updated. |

---

## 4. Identity and source attribution

Every entity carries `source_attribution` — the set of sources that contributed to its current state. This is non-negotiable for two reasons:

1. **Analyst trust** — an analyst looking at a company record needs to know which sources agreed on which attributes. "DealRoom and our internal data agree on funding; Capital IQ disagrees on lead investor" is critical context.
2. **Lineage** — every downstream consumer (AI response, BI visual) inherits source attribution. When an AI summary says "Series B led by Sequoia," the analyst can trace back to the underlying source.

Internal identity (the `_id` columns) is decoupled from any vendor identity. Vendor IDs are stored in a separate `vendor_id_mapping` table. This means a vendor switching identifiers (which happens) does not invalidate platform records.

---

## 5. What is deliberately not modelled

Calling out gaps:

- **Limited Partner (LP) relationships** — Fund-to-LP relationships are valuable but rarely disclosed at sufficient quality for an analytics platform. Modelled as a future extension. Note this is distinct from the `lp_documents` entity (§1.9): those are a fund's own communications *addressed to* its LPs, with no named LP entity or ownership share behind them — see `measures.md`'s vantage-point note for the same distinction on the measures side.
- **Detailed deal terms** — Preferences, liquidation stacks, anti-dilution provisions are not modelled at the level a legal review would require. The platform focuses on capital flows and outcomes, not term mechanics.
- **Public market data** — Public company stock prices, earnings, analyst estimates are out of scope for the platform's private market focus.
- **Fund-level performance** — MOIC and an IRR proxy are computed in the semantic model (not pre-computed in the conformed layer) — see [`measures.md`](measures.md) for the definitions and `design_decisions.md` DD-16 for the IRR-proxy method. **TVPI and DPI are not built, deliberately**: the conformed layer models exits as a terminal `realised_return_multiple`, not dated distribution events, so a DPI would just be a duplicate of the realised share of NAV wearing a more credible-sounding name. `measures.md` names the precondition for adding them honestly (dated distribution/capital-call events in the generator).

---

*Last updated: 2026-08-17. Schema evolves; significant changes are tracked in `design_decisions.md`.*
