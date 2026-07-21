# Fabric Workspace Layout

This document specifies the Fabric workspace structure for the platform implementation. It is implementation-level detail; for the architectural rationale, see [`../docs/architecture.md`](../docs/architecture.md) Section 2.

**As-built vs. target:** the live trial tenant runs each environment tier as **one
workspace** — `pevc-dev`, `pevc-test`, `pevc-prod` (DD-14, extended across tiers per
DD-12's revision) — not workspace-per-layer. This doc leads with that as-built
structure, then documents the target production layout (workspace-per-layer, DD-10) as
the design this build doesn't provision. Don't read the target section as current
state.

---

## Tenant and domain

- **Tenant:** Active Microsoft Fabric trial tenant (portfolio context).
- **Domain:** `Investment Analytics`
  - Created at tenant admin level. Domain admin scoped to this user.
  - The workspace below is organised under this domain for governance grouping.

---

## As-built: one workspace per environment tier

**Capacity:** F2 (trial), shared by all three workspaces below — no per-layer or
per-environment capacity split (see `deployment_pipelines.md` §4's as-built note).
**Purpose:** All layers (ingestion, conformed, Gold, BI) in one workspace per
environment tier. Separation within a tier is by item (lakehouse, notebook), not by
workspace; separation across tiers is `pevc-dev`/`pevc-test`/`pevc-prod`, promoted via
Git (see `deployment_pipelines.md`).

**Items (current, in each of `pevc-dev`/`pevc-test`/`pevc-prod`):**
- Lakehouse: `landing_lakehouse` (+ SQL analytics endpoint) — raw feeds, reference files.
- Lakehouse: `conformed_lakehouse` (+ SQL analytics endpoint) — Delta tables per domain
  entity (see [`../docs/data_model.md`](../docs/data_model.md)).
- Lakehouse: `gold_lakehouse` (+ SQL analytics endpoint) — star schema per DD-15
  (`gold_dim_date`, `gold_dim_company`, `gold_dim_investor`, `gold_fact_investment`).
- Notebooks: `01_schema_validation`, `02_reconciliation`, `03_bitemporal_load`,
  `04_data_quality_assertions`, `05_gold_star_schema` — the conformed + Gold build (see
  [`../notebooks/README.md`](../notebooks/README.md)).
- Semantic Model (DirectLake): `pevc-semantic-model` — over the 4 Gold tables, 5 core
  LP measures (MOIC, IRR proxy per DD-16, NAV proxy, sector concentration, vintage
  performance) plus 2 supporting DAX measures; contract in
  [`../docs/measures.md`](../docs/measures.md).
- Report: `LP Portfolio Performance` — Power BI report consuming the semantic model.

**WS5 AI integration is not additional Fabric workspace items.** DD-13's fusion agent
(Stages A–E, all complete — `ai-integration/`) is a custom Python codebase calling out
to Azure AI Foundry (a separate Azure-subscription resource, not gated by Fabric
capacity); nothing about it lands as a Lakehouse/notebook/etc. inside `pevc-dev` or any
other workspace here.

**RBAC (as-built):** single owner (Admin) per workspace. The Member/Viewer tiering
described in the target layout below isn't exercised — there's one identity operating
each environment (see `ai-integration/agent_common.py`'s docstring for the unrelated
dual-identity situation that applies specifically to WS5's two Azure resources, not to
these Fabric workspaces).

---

## Target production layout (design only — not provisioned)

The remainder of this document describes the workspace-per-layer pattern DD-10
documents as the production-scale choice. None of the workspaces named below
(`ws-ingestion-dev`, `ws-conformed-dev`, `ws-serving-bi-dev`, `ws-serving-ai-dev`) exist
in the trial tenant — everything they'd contain lives in `pevc-dev` today. This section
is a "when you'd build it this way" reference, not a build log.

Four workspaces in the target layout, plus a deployment-pipeline-scoped variant of each
for Dev / Test / Prod (Test and Prod would be placeholders only, even at production
design intent for a portfolio-scale deployment). Fabric Warehouse is a further
deferred extension within that target layout (see
[`../docs/design_decisions.md`](../docs/design_decisions.md) DD-05) — no
`ws-serving-warehouse-*` workspace is part of even the target design; analytical SQL
access is via the Lakehouse SQL endpoint over the conformed/Gold Delta tables in either
layout.

### `ws-ingestion-dev` (target)

**Capacity:** F2 (trial).
**Purpose:** Source-of-truth landing zone for external and internal data feeds.

**Items:**
- Lakehouse: `landing_lakehouse`
  - Shortcuts to ADLS Gen2 paths for representative external feeds (DealRoom-shaped sample data, public market sample data).
  - Internal data folders for synthetic historical deal data.
- Data Pipeline: `internal_deal_data_pipeline`
  - Copies internal historical deal data into landing on a daily schedule.
  - Schema-validated at copy time.
- Notebooks:
  - `source_freshness_check.py` — runs hourly; reports shortcut accessibility and source data age.

**RBAC:**
- Admin: project owner
- Members: none at portfolio scope; in production would be data engineering team
- Viewers: conformed workspace identity (read-only via shortcut)

---

### `ws-conformed-dev` (target)

**Capacity:** F2 (trial).
**Purpose:** Trust boundary. Validated, reconciled, bitemporally-modelled domain data.

**Items:**
- Lakehouse: `conformed_lakehouse`
  - Delta tables for each domain entity (see [`../docs/data_model.md`](../docs/data_model.md)).
  - Shortcut to `ws-ingestion-dev/landing_lakehouse` for read access to landing data.
- Notebooks:
  - `01_schema_validation.py` — validates landing data against expected schemas; routes failures to quarantine table.
  - `02_reconciliation.py` — multi-source reconciliation with conflict surfacing.
  - `03_bitemporal_load.py` — Type 2 SCD updates with effective_date and ingestion_date tracking.
  - `04_data_quality_assertions.py` — post-load DQ checks.
- Data Pipeline: `conformed_build_pipeline`
  - Orchestrates the four notebooks in sequence.
  - Scheduled daily; on-demand triggerable.

**RBAC:**
- Admin: project owner
- Members: none at portfolio scope; in production would be data engineering team
- Viewers: serving workspace identities (read-only via shortcut)

---

### `ws-serving-bi-dev` (target)

**Capacity:** F2 (trial).
**Purpose:** Power BI semantic model and reports.

**Items:**
- Lakehouse: `bi_lakehouse` (lightweight, shortcuts to conformed Delta)
- Semantic Model: `investment_analytics_model` (DirectLake mode)
- Reports:
  - `portfolio_overview.pbix`
  - `pipeline_dashboard.pbix`
  - `vintage_performance.pbix`

**RBAC:**
- Admin: project owner
- Members: BI developers
- Viewers: end-user analysts

---

### `ws-serving-ai-dev` (target)

**Capacity:** F2 (trial).
**Purpose:** AI integration layer with Azure OpenAI.

**Items:**
- Lakehouse: `ai_serving_lakehouse` (shortcuts to conformed)
- Notebooks:
  - `ai_retrieval_functions.py` — structured retrieval against conformed.
  - `prompt_templates/` — versioned prompt templates.
  - `structured_output_schemas/` — JSON schemas for AI responses.
  - `inference_audit.py` — captures prompt, response, validation status to audit table.
- External dependencies:
  - Azure OpenAI deployment (in connected Azure subscription)
  - Azure AI Search index for document embeddings

**RBAC:**
- Admin: project owner
- Members: AI engineering team (in production)
- Viewers: API service principals for application consumption

---

## Capacity allocation rationale

**As-built:** everything shares the single F2 trial capacity behind `pevc-dev` — no
per-layer allocation exists to reason about yet.

**Target production sizing**, if the workspace-per-layer layout above were built:

| Workspace | Production capacity sizing | Why |
|---|---|---|
| Ingestion | Small, burstable | Mostly idle; bursts on ingestion schedule. |
| Conformed | Medium, scheduled high | Daily build window needs throughput; idle outside. |
| BI serving | Small | DirectLake offloads compute to the source Lakehouse. |
| AI serving | Medium, sustained | LLM call orchestration and retrieval are concurrent. |

If Warehouse serving is reopened (see DD-05), it would size Medium/sustained — analyst
query patterns are unpredictable but moderate.

---

## Git integration

**As-built:** all three environment workspaces are Git-connected to this repository
(GitHub) at the **same** folder, `fabric/pevc/` — `pevc-dev`↔`dev` branch,
`pevc-test`↔`test`, `pevc-prod`↔`main` — there's no per-layer folder split, and
deliberately no per-environment folder split either (see
[`fabric/pevc/README.md`](../fabric/pevc/README.md) and `deployment_pipelines.md` for
why a matching path across branches is what makes Git-driven promotion a plain merge).
Fabric's Commit operation writes one subfolder per workspace item there
(`<name>.Notebook/`, `<name>.Lakehouse/`, `<name>.SemanticModel/`, `<name>.Report/`); it
is not hand-edited.

**Target production layout**, if workspace-per-layer were built, would Git-connect each
workspace to a workspace-scoped folder:

```
fabric-pe-vc-analytics/
├── workspaces/
│   ├── ws-ingestion/
│   ├── ws-conformed/
│   ├── ws-serving-bi/
│   └── ws-serving-ai/
```

Promotion across Dev → Test → Prod is Git-driven (PR merge between branches), not the
Fabric deployment pipeline's Deploy button — implemented and verified end to end at
portfolio scope, see [`deployment_pipelines.md`](deployment_pipelines.md) for the full
account (including why both mechanisms running independently was tried first and
produced a real duplication risk).

---

*Last updated: 2026-07-21. Layout reflects portfolio implementation (DD-14, extended across environment tiers per DD-12); production sizing and workspace-split notes are target-design guidance, not built.*
