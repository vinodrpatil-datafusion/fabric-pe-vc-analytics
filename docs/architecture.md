# Architecture — PE/VC Investment Analytics Platform on Microsoft Fabric

This document describes the end-to-end architecture of the platform: workspace layout, data flow, component responsibilities, and the rationale behind each significant decision.

For decision rationale specifically, see [`design_decisions.md`](design_decisions.md). For the domain schema, see [`data_model.md`](data_model.md).

---

## 1. Architectural principles

The architecture is shaped by five principles, applied in order of precedence when they conflict.

**1.1 Data quality enforced upstream of AI.** The LLM layer reasons over validated, reconciled, source-attributed data. The conformed layer is the trust boundary; nothing reaches AI before it is enforced there.

**1.2 Lineage as substrate, not feature.** Every data point carries source, ingestion timestamp, and effective-date metadata from landing through serving. Audit and reproducibility are continuously available, not retrofitted on incident.

**1.3 Point-in-time integrity is mandatory.** Investment data is bitemporal. The platform distinguishes `effective_date` (when the fact became true in the world) from `ingestion_date` (when it became known to the platform). Screening and IC outputs are reproducible against the data state at any historical point.

**1.4 Relational density modelled explicitly.** PE/VC is a graph problem at heart. Investor → fund → portfolio company → co-investor → board member relationships are first-class, not derived through application-layer joins.

**1.5 Governance boundaries are explicit, not implicit.** Raw, conformed, and serving are kept separated — as distinct Fabric workspaces with distinct RBAC in a team/production deployment (DD-10), or as distinct lakehouses/items within a single workspace per environment tier at the trial scope this build actually runs at (DD-14, extended per DD-12). Either way, cross-boundary access is through shortcuts (read-only) and explicit promotion paths, not ad-hoc reads across the data-quality boundary.

---

## 2. Workspace layout

> **As-built note (DD-14, extended across tiers per DD-12):** the live trial tenant runs
> each environment tier as **one Fabric workspace** (`pevc-dev`/`pevc-test`/`pevc-prod`)
> — landing and conformed lakehouses, all conformed-layer notebooks, and Gold/BI
> artefacts together (WS5's AI layer is a separate Python codebase, not a Fabric
> workspace item — see §2.3.3). The sections below
> describe the **target, production-scale layout** (DD-10) — workspace-per-layer with
> distinct RBAC — which this build documents but does not provision. Where the target
> design says "workspace," the as-built equivalent is "lakehouse/item within
> `pevc-dev`," with data-quality boundaries enforced by item separation rather than
> workspace RBAC. See [`../infrastructure/workspace_layout.md`](../infrastructure/workspace_layout.md)
> for the as-built structure in full.

Three primary workspaces, organised under an **Investment Analytics** Fabric domain, in
the target production layout.

### 2.1 Ingestion workspace (target; as-built: `landing_lakehouse` in `pevc-dev`)

**Purpose:** Receive raw external and internal data with no transformation. Source-of-truth landing zone.

**Contents:**
- OneLake lakehouse: `landing_lakehouse`
- Shortcuts to external storage (ADLS Gen2 for DealRoom feeds, additional shortcuts for vendor-equivalents)
- Schema validation notebooks
- Source attribution metadata tables

**Access:** Data engineering team write; conformed workspace read via shortcut. No direct analyst or AI access. (As-built: item-level permissions on `landing_lakehouse` within `pevc-dev`, single owner at trial scope.)

**Why isolated:** Raw data may contain PII, contractual terms under NDA, or unvalidated vendor outputs. Quarantining it protects every downstream consumer.

### 2.2 Conformed workspace (target; as-built: `conformed_lakehouse` in `pevc-dev`)

**Purpose:** The trust boundary. Data here is validated, reconciled, deduplicated, source-attributed, and bitemporally modelled.

**Contents:**
- OneLake lakehouse: `conformed_lakehouse` (Delta tables)
- Reconciliation logic (Spark notebooks / Dataflow Gen2)
- Bitemporal slowly-changing-dimension implementations
- Data quality assertion notebooks
- Domain entity tables (companies, funding rounds, investors, investments, people, deals, documents)

**Access:** Data engineering write; serving workspaces read; AI layer reads from here only. (As-built: same single-owner item-level access within `pevc-dev` as 2.1.)

**Why this is the trust boundary:** Everything that consumes data — analytical workloads, BI semantic models, AI integrations — reads from conformed. Quality enforced once, consumed by many.

### 2.3 Serving workspaces (target; as-built: same `pevc-dev` workspace)

Two serving paths consume the conformed/Gold layer for different access patterns.
Fabric Warehouse is a documented, deferred extension path — not built at portfolio
scope (see DD-05) — because DirectLake plus the Lakehouse SQL endpoint already cover
the query patterns this build needs, and no build session provisions or populates it.

#### 2.3.1 Analytical serving — Lakehouse SQL endpoint

**Purpose:** Ad-hoc analyst SQL and ETL/pipeline inspection over the Gold star schema.

**Why the Lakehouse SQL endpoint, not Warehouse:** At portfolio query volume and
complexity, the SQL endpoint's read-only Delta access is sufficient. Warehouse's more
mature optimiser (joins across large fact tables, window functions, complex
aggregations) would earn its keep at sustained analytical load this build doesn't
generate — see DD-05 for the "when you'd add it back" case.

**Contents:**
- Read access to Gold Delta tables directly (no shortcut hop; same Lakehouse)
- Ad-hoc query surface for pipeline/DQ inspection during development

#### 2.3.2 BI semantic serving — DirectLake

**Purpose:** Power BI semantic model for analyst self-service.

**Why DirectLake:** Eliminates import refresh cycles, reads Delta directly, sub-second performance at semantic-model scale. The semantic model is the version-of-truth for measures and hierarchies; analysts consume through Power BI without parallel datasets drifting from source.

**Contents:**
- `pevc-semantic-model` (DirectLake semantic model, built — as-built name differs from
  the `investment_analytics.bim` placeholder used earlier in this doc's drafting)
- DAX measures encoding institutional definitions (IRR proxy, MOIC, vintage cohorts) —
  full contract, definitions, and caveats in [`measures.md`](measures.md)
- Row-level security tied to workspace RBAC

#### 2.3.3 AI serving — Azure OpenAI integration layer

**Purpose:** Grounded AI workloads — retrieval, summarisation, structured insight generation.

**Why a separate workspace (target design):** AI workloads have different access patterns (low-latency point-lookups + vector retrieval), different governance requirements (prompt/response logging, model versioning), and different cost models (per-token, not per-CU). As actually built (WS5, complete — see `ai-integration/`), this isn't a Fabric workspace concern at all: the fusion agent is a separate Python codebase calling Azure AI Foundry (vector store + LLM), reading only from the conformed/Gold layer's Delta tables and the semantic model, not living inside any `pevc-*` workspace as an item. The cost/governance separation this target-design argument describes doesn't bind for a single-tenant, single-owner build either way.

**Contents:**
- Retrieval functions against conformed Delta
- Vector index for document embeddings (Azure AI Search externally; future migration to Fabric vector capabilities when GA)
- Prompt template library with version control
- Structured-output schemas for AI responses
- Inference audit log (separate from data lineage)

---

## 3. Data flow

### 3.1 Ingestion to landing

External data sources are accessed through **OneLake shortcuts** to underlying storage, not copied into Fabric.

**Why shortcuts:**
- Single source of truth — no duplication, no refresh drift
- Lineage clarity — Purview traces back to original source through the shortcut
- Cost — no storage duplication
- Freshness — reads always see the latest in the source

**Trade-off acknowledged:** Shortcuts introduce a dependency on source availability and tolerate source-side schema changes poorly. The validation layer (Section 3.2) is the compensating control.

For internal historical deal data and any feed that requires transformation before landing, **Fabric Data Pipelines** (inheriting ADF heritage) handle the copy. Same pipeline patterns I've operated in production at a European private-banking group, translated to Fabric's pipeline model.

### 3.2 Landing to conformed

Three stages, in order. Each is independently observable.

**Stage A — Schema validation.** Spark notebook runs against the landed data. Validates: column presence, type conformance, null tolerances per column, referential keys, source freshness. Validation failures route to a quarantine table; downstream stages do not see invalid rows.

**Stage B — Reconciliation.** Multi-source overlaps (the same company appearing in DealRoom, Capital IQ, and internal data) are reconciled deterministically. The pattern: surface conflicts rather than silently pick winners. A `reconciliation_status` column carries `clean`, `conflict_resolved`, or `conflict_flagged` per row, with the resolution path logged.

**Stage C — Bitemporal load.** Conformed Delta tables are loaded with both `effective_date` (when the fact became true in the world) and `ingestion_date` (when it became known to the platform). Historical corrections (e.g., a funding round restated months after disclosure) are handled as Type-2 SCD updates with both dates tracked.

### 3.3 Conformed to serving

In the target design, serving workspaces read conformed Delta tables via OneLake
shortcuts, each exposing its own access surface without duplicating storage. At trial
scope (DD-14, extended per DD-12), serving items read the same `conformed_lakehouse`
directly within whichever of `pevc-dev`/`pevc-test`/`pevc-prod` they belong to — no
shortcut hop needed since there's no workspace boundary to cross within a tier. This
applies to the semantic model (reads Gold directly). WS5's AI layer is different: it's
not a Fabric item reading Delta tables at all, but a separate Python codebase
(`ai-integration/`) that queries the DirectLake semantic model over the Power BI REST
API (structured leg) and Azure AI Foundry vector stores (document leg) — see §2.3.3 and
§3.4.

### 3.4 AI inference flow (target design)

**As-built (WS5, complete):** the actual fusion agent (`ai-integration/fusion_agent.py`)
is simpler than the seven-step flow below — it classifies a question as structured,
document, or hybrid, dispatches to the structured agent (function-calling against
`pevc-semantic-model`) and/or document agent (Foundry `file_search` over the LP
document corpus), and synthesises hybrid answers; there's no separate relational-
expansion hop, no dedicated inference audit table (see `governance.md` §4.2), and
citation checking happens in `evaluate_agents.py`'s oracle-based harness, not as an
inline output-validation step. The flow below is the original target design; read it as
that, not as a description of what was built.

For an AI-driven workload (e.g., "summarise the funding history of company X in the context of similar companies in our portfolio"):

1. **Structured retrieval.** Point-lookup against conformed Delta for company X's funding rounds, board, current investors.
2. **Relational expansion.** Multi-hop query for portfolio companies in the same sector with comparable round histories.
3. **Vector retrieval.** Optional — fetch related document embeddings (memos, news) for unstructured context.
4. **Prompt construction.** Structured prompt template enforces source-attribution requirements on outputs. Every claim in the response must cite a specific source row.
5. **LLM call.** Azure OpenAI with structured output schema (JSON schema enforcement).
6. **Output validation.** Schema validation on the response. Citation validation — every cited row must exist in retrieval context. Schema or citation failures route to human review queue.
7. **Audit logging.** Prompt version, model version, retrieval context hash, response, validation status logged to inference audit table.

---

## 4. Governance plane

In the target design, governance is layered across every workspace, not concentrated
in one. At trial scope (DD-14), it's layered across every **item** within the single
`pevc-dev` workspace instead — the boundary moved from workspace to item, not away.

### 4.1 Workspace RBAC (target); item-level RBAC (as-built)

Target: three role tiers per workspace — Admin, Member, Viewer — with cross-workspace access explicit (no implicit promotion) and the conformed workspace gating everything downstream. As-built: `pevc-dev` has a single owner (Admin), so the multi-role tiering isn't exercised yet; the conformed lakehouse item still conceptually gates everything downstream, enforced by the pipeline order (Stage A → D) rather than by RBAC on a separate workspace.

### 4.2 Sensitivity labels

Microsoft Purview sensitivity labels propagate through OneLake. Labels are applied at the table or column level in the conformed layer and inherited through shortcuts to serving workspaces. Power BI reports inherit and enforce labels on visuals.

### 4.3 Lineage

End-to-end lineage from external source through to BI visual or AI response is designed
around Purview integration with Fabric (designed, not yet wired up in the trial tenant
— see `docs/governance.md` §3). Lineage includes:
- Data lineage — source → landing → conformed → serving
- Inference lineage — for AI responses, the retrieval context, model version, and prompt version

### 4.4 Domain organisation

Investment Analytics is a Fabric **domain**. Domain-level governance allows the investment data estate to be separated from any other data estate the broader platform might serve — important for multi-business institutional contexts.

### 4.5 Audit

Three audit substrates:
- **Data access audit** — who queried what, when (Fabric native).
- **Inference audit** — every AI invocation with reproducibility metadata.
- **Decision audit** — for BI consumers, which reports were viewed and exported; for AI consumers, which outputs were accepted, modified, or overridden.

---

## 5. Cross-cutting concerns

### 5.1 CI/CD via Git

Fabric items (notebooks, lakehouses, semantic models, reports) are managed through Git integration — all three environment workspaces connected (`pevc-dev`↔`dev`, `pevc-test`↔`test`, `pevc-prod`↔`main`, this repo on GitHub, shared folder `fabric/pevc/`). Promotion across Dev → Test → Prod is Git-driven (PR merge between branches, each workspace's own Git sync pulling the merge in — DD-12's revision), not the Fabric deployment pipeline's Deploy button; both mechanisms running independently produced a real duplication risk on the first attempt. Fully implemented and verified end to end — data, notebooks, semantic model, and reports all working independently in Test/Prod — see [`infrastructure/deployment_pipelines.md`](../infrastructure/deployment_pipelines.md).

### 5.2 Capacity management

In the target design, Fabric capacity is allocated per workspace with elasticity to handle ingestion bursts (e.g., quarterly bulk refreshes from external sources) without provisioning for peak permanently — the BI serving workspace would carry independent capacity from the AI workspace since their cost models differ. At trial scope (DD-14), all items share the single F2 capacity backing `pevc-dev`; per-path capacity isolation is one of the things a production split (DD-10) would buy back.

### 5.3 Multi-tenancy (designed but not implemented)

For a production multi-tenant deployment — e.g., a platform serving multiple investment teams within an institution, or multiple institutional customers — the architecture extends through:

- Domain-per-tenant for governance isolation
- Workspace-per-tenant within each domain for compute and storage isolation
- Per-tenant encryption keys at the OneLake level
- Mandatory tenant predicates at the serving layer (row-level security if Warehouse is added, role-based filtering in semantic models)
- Tenant-scoped AI context — no cross-tenant retrieval, separate prompt-time scoping

This is documented as design but not implemented in the portfolio build (which is single-tenant by design).

---

## 6. What this architecture deliberately does not do

Listing the trade-offs explicitly:

- **No real-time streaming.** External investment data sources are batch by nature (daily refreshes typical). Fabric Real-Time Intelligence is not engaged. Adding it would be straightforward for material event detection (M&A news, leadership change) but is not justified for the core analytics workflow.
- **No fine-tuning.** The AI layer uses Azure OpenAI with prompting and structured outputs, not fine-tuned models. Fine-tuning would be the natural next step for domain vernacular precision; it's deferred to keep the portfolio scope tractable.
- **No formal knowledge graph database.** Relational density is modelled in the conformed Delta layer with relationship tables and Spark graph operations. A dedicated graph database (Neo4j, Cosmos Gremlin) would be the production choice for sustained multi-hop traversal performance; the Delta-based approach is sufficient for portfolio scale.
- **No Fabric Warehouse.** Analytical serving is DirectLake plus the Lakehouse SQL endpoint (see DD-05). Warehouse's mature T-SQL optimiser would be the right addition at sustained analytical load or for a dedicated analyst team running continuous ad-hoc SQL; neither applies at portfolio scale, and no build session provisions it.
- **No physical multi-tenancy.** Single-tenant by design. Multi-tenancy is documented as extension path, not built.

---

## 7. Mapping to investment workflows

The architecture supports the four core PE/VC workflows:

- **Sourcing** — multi-source company discovery, semantic search over deal corpus, relationship-driven warm-intro identification.
- **Screening** — structured filtering with bitemporal queries ("companies at Series A in Q1 2024 in our active sectors"), comparable-company analysis via graph traversal.
- **Due diligence** — first-pass memo generation via AI layer over validated company data; analyst review and override loop.
- **Portfolio monitoring** — recurring analytics on portfolio company performance, sector-level rollups, scenario analysis.

Each workflow consumes the same conformed data layer through different serving paths (BI for portfolio monitoring, AI for memo generation, Lakehouse SQL endpoint for ad-hoc analytical queries).

---

*Last updated: 2026-08-17. This is a living architectural document for an active portfolio project.*
