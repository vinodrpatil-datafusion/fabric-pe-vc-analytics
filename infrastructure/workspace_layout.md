# Fabric Workspace Layout

This document specifies the Fabric workspace structure for the platform implementation. It is implementation-level detail; for the architectural rationale, see [`../docs/architecture.md`](../docs/architecture.md) Section 2.

---

## Tenant and domain

- **Tenant:** Active Microsoft Fabric trial tenant (portfolio context).
- **Domain:** `Investment Analytics`
  - Created at tenant admin level. Domain admin scoped to this user.
  - All workspaces below are organised under this domain for governance grouping.

---

## Workspaces

Three primary workspaces (ingestion, conformed, serving), plus a
deployment-pipeline-scoped variant of each for Dev / Test / Prod (Test and Prod
placeholders only at portfolio scope). Serving splits into BI and AI workspaces below.
Fabric Warehouse is a documented, deferred extension (see
[`../docs/design_decisions.md`](../docs/design_decisions.md) DD-05) — no
`ws-serving-warehouse-*` workspace is provisioned. Analytical SQL access at portfolio
scope is via the Lakehouse SQL endpoint directly over the conformed/Gold Delta tables.

### `ws-ingestion-dev`

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

### `ws-conformed-dev`

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

### `ws-serving-bi-dev`

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

### `ws-serving-ai-dev`

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

At portfolio scope, all workspaces share trial capacity. In a production deployment, capacity would be allocated as:

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

All workspaces are Git-connected to a single repository with workspace-scoped folders:

```
fabric-pe-vc-analytics/
├── workspaces/
│   ├── ws-ingestion/
│   ├── ws-conformed/
│   ├── ws-serving-bi/
│   └── ws-serving-ai/
```

Promotion across Dev → Test → Prod is via Fabric deployment pipelines. See [`deployment_pipelines.md`](deployment_pipelines.md) (in progress).

---

*Last updated: 2026-07-11. Layout reflects portfolio implementation; production sizing notes are guidance.*
