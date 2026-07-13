# Design Decisions

This log captures the significant architectural decisions made for the platform, the alternatives considered, and the rationale. It is intended to be read alongside [`architecture.md`](architecture.md).

Format: each decision lists the choice, the alternatives, the rationale, and any explicit trade-offs accepted. Decisions are numbered for cross-reference.

---

## DD-01. Microsoft Fabric as the platform

**Choice:** Microsoft Fabric (OneLake, Lakehouse, Warehouse, DirectLake, Fabric Data Pipelines, Power BI).

**Alternatives considered:**
- Azure Synapse Analytics (dedicated SQL + serverless + Spark pools)
- Azure Databricks + Power BI
- Snowflake on Azure

**Rationale:**
Fabric unifies the Lakehouse and Warehouse paradigms over a single OneLake substrate. For an investment analytics workload with mixed structured (companies, rounds, investments) and semi-structured (memos, news) data, the ability to land once in OneLake and serve through multiple compute engines avoids the data copy proliferation typical in lambda-style architectures. DirectLake collapses the BI refresh cycle entirely, which is consequential for analyst-facing dashboards that consume Delta-native data.

**Trade-offs accepted:**
- Fabric's relative maturity vs Synapse — some workloads (complex Spark optimisation, custom ML pipelines) are better served by Databricks today. Mitigated by the fact that the investment analytics workload here is structured-data-heavy with moderate Spark needs.
- Vendor lock-in to Microsoft ecosystem — acceptable for an Azure-native enterprise context.

---

## DD-02. OneLake shortcuts for external source ingestion

**Choice:** External data sources (DealRoom feeds, vendor data) accessed via OneLake shortcuts to underlying storage, not copied into Fabric.

**Alternatives considered:**
- Copy ingestion via Fabric Data Pipelines into a landing Lakehouse
- Streaming ingestion via Eventstream
- Direct query through linked services

**Rationale:**
For external feeds that are already landed in cloud storage (typical pattern: vendor delivers to S3 or ADLS Gen2), shortcuts give Fabric query access without storage duplication. Lineage traces back to the source through the shortcut. Refresh is automatic — reads see latest source state. Cost is single-stored.

**Trade-offs accepted:**
- Source schema drift is felt immediately rather than buffered. Compensated by the Stage A schema validation in the conformed pipeline.
- Source availability becomes a runtime dependency. Acceptable because the alternative — periodic copies — introduces freshness lag that investment analysts complain about.

**When this decision would not apply:**
For internal historical data, on-premises sources, or feeds requiring transformation-on-ingest, copy ingestion via Fabric Data Pipelines is the right pattern. Decision DD-02 applies specifically to external feeds already in cloud-native storage.

---

## DD-03. Delta Lake on Lakehouse as the conformed layer

**Choice:** Conformed layer implemented as Delta tables in a Fabric Lakehouse.

**Alternatives considered:**
- Conformed layer in Warehouse (T-SQL native tables)
- Parquet without Delta transaction log
- Iceberg

**Rationale:**
Three properties matter for the conformed layer:
1. **Schema evolution** — investment data schemas change (DealRoom adds fields, new sectors get classified, regulatory disclosures expand). Delta handles schema evolution natively.
2. **Time travel** — reproducibility of historical analyses depends on being able to query the data state at a point in time. Delta's time travel supports this without separate snapshot infrastructure.
3. **AI workload friendliness** — Spark and Python read Delta natively for AI preprocessing; Warehouse T-SQL is more constrained for that pattern.

Analytical serving is DirectLake plus the Lakehouse SQL endpoint at portfolio scope (see DD-05), but the conformed layer where data quality and bitemporal modelling are enforced wants Delta's flexibility regardless of which SQL surface eventually serves it.

**Trade-offs accepted:**
- Delta on Lakehouse is read via SQL endpoint or Spark; the SQL endpoint has fewer optimiser features than Warehouse would. Acceptable at portfolio query volume and complexity (see DD-05); Warehouse via shortcut from the conformed Lakehouse remains the documented path if that changes.

---

## DD-04. Bitemporal modelling for time-sensitive entities

**Choice:** Funding rounds, investments, valuations, and any entity where the announcement-vs-effective distinction matters are modelled with both `effective_date` and `ingestion_date` columns.

**Alternatives considered:**
- Single-temporal modelling (ingestion_date only) — common pattern
- Event-sourced modelling with full event log

**Rationale:**
Investment data is point-in-time, and the announcement-vs-effective gap is material. A Series B announced in March 2025 may have closed in January 2025; an IC reviewing the company in February 2025 should not see the round as having occurred. Single-temporal modelling makes this distinction impossible. Event-sourced modelling solves it but introduces complexity disproportionate to the use case.

Bitemporal columns on the relevant tables give the right resolution at acceptable complexity.

**Trade-offs accepted:**
- Storage overhead from SCD Type 2 patterns on bitemporal updates. Acceptable; investment data volumes are modest.
- Query complexity — bitemporal queries are non-trivial. Mitigated by encapsulating the common "as-of-date" patterns in DAX measures and Lakehouse SQL endpoint views, so analysts don't write the bitemporal logic each time.

---

## DD-05. Analytical serving is DirectLake + Lakehouse SQL endpoint; Warehouse deferred

**Status:** Revised 2026-07-11. Originally this decision put Fabric Warehouse in the
serving path for analytical SQL workloads. That conflicted with the locked build
constraint that Gold is Lakehouse-only (Delta + PySpark, DirectLake — no Warehouse Gold)
and, in practice, no session in the build plan ever provisioned or populated a Warehouse.
Documenting an active serving path that nothing builds is worse than not having one;
this entry now records the as-built decision and preserves the original rationale below
as the "when you'd add it back" case.

**Choice:** At portfolio scope, analytical serving is DirectLake (Power BI semantic
model) plus the Lakehouse SQL endpoint for ad-hoc query and ETL inspection. Fabric
Warehouse is **not provisioned**; `ws-serving-warehouse-dev` does not exist as a built
workspace.

**Alternatives considered:**
- Fabric Warehouse as a dedicated analytical SQL serving layer (the original DD-05 choice)
- Lakehouse SQL endpoint as the only SQL surface (the choice actually made)
- Hybrid — some workloads to each

**Rationale:**
The Gold star schema (WS3) is built once, as Delta tables in a Gold Lakehouse, and
DirectLake reads it directly for BI — no import cycle, no second copy. The remaining
need — ad-hoc analyst SQL, ETL inspection — is served adequately by the Lakehouse SQL
endpoint at this data volume and query complexity. Standing up a Warehouse for a query
pattern DirectLake and the SQL endpoint already cover would be a second copy of Gold
with no session in the plan to build or maintain it.

**When Warehouse would be the right addition (not built here):**
Warehouse's SQL optimiser earns its keep at sustained analytical load the Lakehouse SQL
endpoint doesn't handle well — heavy multi-fact joins and window functions at scale,
a dedicated analyst team running ad-hoc queries continuously (not just BI-mediated
access), or a need for stored procedures / materialised aggregation tables as a
governed query surface distinct from Gold. None of those apply at portfolio scope. If
they did, the original pattern still holds: Warehouse reads Gold via OneLake shortcut,
single copy of data, two SQL surfaces with different optimisation characteristics.

**Trade-offs accepted:**
- No dedicated analytical-SQL surface with a mature optimiser for complex multi-fact
  aggregations; acceptable because portfolio-scale queries don't stress the Lakehouse
  SQL endpoint.
- If a future session reopens Warehouse, `architecture.md` §2.3.1, `CLAUDE.md`'s flow
  diagram, `infrastructure/workspace_layout.md`, and this entry all need to move
  together — that was the drift this revision fixes.

---

## DD-06. DirectLake for the Power BI semantic model

**Choice:** Power BI semantic model in DirectLake mode reading from the conformed Lakehouse.

**Alternatives considered:**
- Import mode with scheduled refresh from Warehouse
- DirectQuery against Warehouse
- Composite model

**Rationale:**
DirectLake eliminates the import refresh cycle entirely. The semantic model reads Delta directly, with sub-second query performance at typical analyst-dashboard scale. There is no refresh lag, no parallel data copy, no risk of the semantic model drifting from the source.

For an investment context where analyst trust depends on dashboards reflecting the current state of data, DirectLake is the right default.

**Trade-offs accepted:**
- DirectLake has constraints — calculated columns are limited, model size has upper bounds, fallback to DirectQuery happens for unsupported features. For the platform's current semantic model, these constraints are non-binding.
- DirectLake performance is sensitive to Delta table optimisation (file size, V-Order). The conformed layer maintenance routines explicitly run OPTIMIZE on serving-relevant tables.

---

## DD-07. Graph-aware modelling in Delta, not a dedicated graph database

**Choice:** Investor-to-company-to-co-investor relationships modelled in the conformed layer as explicit relationship tables, with multi-hop queries executed via Spark graph operations or T-SQL CTEs.

**Alternatives considered:**
- Dedicated graph database (Neo4j, Cosmos DB Gremlin API)
- Property graph on Lakehouse via Spark GraphFrames

**Rationale (for portfolio scope):**
Relationship tables in Delta give the relational density without operating a second database. Multi-hop queries are achievable via CTEs in T-SQL or GraphFrames in Spark. For portfolio scale and the depth of typical queries (2–4 hops), this is sufficient.

**Why a graph database would be the production choice:**
At sustained query depth (5+ hops) or query frequency (every analyst session running multi-hop traversals), dedicated graph databases pay for themselves through traversal-optimised indexes. The architecture document (Section 6) calls this out explicitly as a deferred choice, not a wrong one.

**Trade-offs accepted:**
- Query performance for deep multi-hop traversals is bounded by Spark / T-SQL recursion limits and execution cost.
- Modelling complexity is in application code (the CTEs or GraphFrames calls), not in the storage layer.

---

## DD-08. Azure OpenAI integration over conformed data only

**Choice:** The AI layer reads only from the conformed Delta layer. It never accesses raw landing data.

**Alternatives considered:**
- AI layer reads from raw landing for "freshest" data
- AI layer has its own data abstraction independent of conformed

**Rationale:**
This is a non-negotiable architectural principle (Principle 1.1 in `architecture.md`). The conformed layer is the trust boundary; AI reasoning on validated, reconciled, source-attributed data is the only way to bound hallucination risk to acceptable levels. Allowing the AI layer to bypass conformance creates a path where untrusted data drives AI output.

**Trade-offs accepted:**
- Latency — AI sees data only after the conformed pipeline has run, which is daily for most sources.
- Implementation discipline — the temptation to "just point the LLM at the raw feed" for a specific use case has to be resisted. Architecturally enforced through workspace RBAC: AI workspace identity cannot read landing workspace.

---

## DD-09. Structured outputs and citation enforcement on AI responses

**Choice:** Every AI response is constrained to a JSON schema. Every claim in the response must cite a specific row from the retrieval context.

**Alternatives considered:**
- Free-form text responses
- Schema enforcement without citation requirement
- Citation only, no schema

**Rationale:**
Structured outputs eliminate a class of hallucination by making it impossible for the LLM to invent fields. Citation enforcement makes verifiability operational — the analyst can check every claim against its source. Together they shift the AI layer from "trust the LLM's text" to "trust the LLM's structured summary of validated data."

**Trade-offs accepted:**
- Some response patterns (open-ended exploration, brainstorming) are not well-served by strict schema enforcement. For those workloads, a separate less-constrained surface would be provided. The default for analytical and IC-grade outputs is strict.
- Implementation effort — schema design and citation validation logic is non-trivial. Required investment for production trust.

---

## DD-10. Workspace separation as governance boundary

**Status:** Revised 2026-07-13. This entry records the production-target governance
pattern. The as-built trial tenant uses a single workspace instead — see DD-14 for the
portfolio-scope decision and the reconciliation this revision makes with reality.

**Choice:** Ingestion, conformed, and serving in separate Fabric workspaces with explicit RBAC and shortcut-based read access.

**Alternatives considered:**
- Single workspace with folder-level organisation
- Two workspaces (raw + everything else)

**Rationale:**
Workspaces in Fabric are the unit of RBAC, capacity allocation, and Git source control. Aligning them with the data quality boundary (raw, conformed, serving) gives a clean mapping from organisational governance to technical enforcement. A developer who has access to serving workspaces does not automatically have access to landing workspaces; promotion paths are explicit.

**Trade-offs accepted:**
- More workspaces to manage. Acceptable; the operational overhead is small relative to the governance value.
- Cross-workspace dependencies need to be designed (shortcut paths, deployment pipeline ordering). This is by design — making the dependencies explicit is the point.
- **Not applied at portfolio scope** (DD-14): a single trial-tenant admin managing one F2
  capacity gets none of the multi-developer RBAC benefit this decision is optimised for.
  The pattern remains the right answer for a team-operated production deployment; it's
  documented here, not built, at this scope.

---

## DD-11. Microsoft Purview for lineage, not custom

**Status:** Designed, not implemented in the trial tenant — consistent with the README
roadmap ("Microsoft Purview lineage integration").

**Choice:** End-to-end data lineage via Microsoft Purview integration with Fabric.

**Alternatives considered:**
- OpenLineage with custom collector
- No formal lineage tooling; manual documentation

**Rationale:**
Purview's Fabric integration provides automatic lineage from source through to BI artefacts and AI responses without custom instrumentation. For a regulated-environment-targeted platform, the alternative of "we have lineage when we need it" is operationally untenable.

**Trade-offs accepted:**
- Purview licensing cost. Acceptable for the target deployment context.
- Some custom AI-specific lineage (prompt versions, retrieval context hashes) is captured outside Purview in a custom inference audit log. Purview integration here is documented as a roadmap item.

---

## DD-12. CI/CD through Git integration and deployment pipelines

**Choice:** Fabric items (notebooks, pipelines, semantic models, Lakehouse definitions) tracked in Git, promoted across Dev/Test/Prod workspaces via Fabric deployment pipelines.

**Alternatives considered:**
- Manual workspace cloning
- Custom CI/CD using Fabric APIs

**Rationale:**
Git integration in Fabric reached production maturity in 2024-2025 and is the right pattern for any platform expecting iteration. Deployment pipelines handle the workspace-to-workspace promotion with environment-specific parameterisation. Custom CI/CD via Fabric APIs is more flexible but is not yet justified for the platform's scope.

**Status:** In progress in the implementation. Design documented in [`../infrastructure/deployment_pipelines.md`](../infrastructure/deployment_pipelines.md).

---

## DD-13. Foundry-composed fusion agent for AI integration (WS5 Option B)

**Status:** Added 2026-07-11. This commits an AI integration pattern that had been
discussed but not formally recorded, reopening the "multiple AI patterns" question with
a concrete choice rather than leaving it a deferred line item.

**Choice:** AI integration is a **fusion agent** that routes each question to one or
both of two independent retrieval legs, then composes the result:
- **Structured leg** — a Fabric Data Agent over the Gold star schema, answering
  NL2SQL-shaped questions (metrics, filters, aggregations) directly against Delta
  tables.
- **Unstructured leg** — Foundry IQ indexing a synthetic LP document corpus (quarterly
  letters, capital call notices, memos), answering document-grounded questions with
  citations.
- **Routing** — structured questions go to the Data Agent, document questions go to
  Foundry IQ, hybrid questions go to both with the fusion agent synthesising a single
  cited answer.

**Alternatives considered:**
- **Data Agent only** — structured NL2SQL with no document retrieval. Simpler, but
  can't answer anything grounded in LP letters, memos, or capital call notices — a
  material gap for the due-diligence and portfolio-monitoring workflows in
  `architecture.md` §7.
- **Foundry IQ only** — document retrieval with no structured query path. Can't answer
  precise metric questions ("MOIC by vintage") without either hallucinating numbers or
  falling back to citing a document that happens to contain them — worse grounding for
  exactly the questions structured retrieval answers cleanly.
- **Single monolithic agent with tool access to both** — one agent given both a SQL
  tool and a retrieval tool, deciding per-turn what to call. Simpler to stand up, but
  routing logic and failure modes are opaque inside one prompt; harder to evaluate each
  leg's accuracy independently — the eventual evaluation needs per-leg scores, not just
  a blended end-to-end number.

**Rationale:**
Structured and unstructured investment questions have different failure modes and need
different grounding strategies. Keeping the two legs independently retrievable and
independently evaluable (groundedness + citation-accuracy scored per leg, not just
blended) is what makes the eventual evaluation numbers mean something. The fusion agent
is the minimum routing layer that gets a hybrid answer without collapsing that
separation. This still honours DD-08 — both legs read only from the conformed/Gold
layer: the Data Agent queries Gold directly, and the LP document corpus is generated
with every document required to reference existing Gold dimension keys (fund/company/
round IDs), so Foundry IQ's index is itself traceable back to conformed data rather than
an independent, unvalidated source.

**Trade-offs accepted:**
- Two retrieval systems to build, index, and maintain instead of one — accepted because
  the alternative (pick one) leaves a workflow category unanswerable or poorly grounded.
- Routing errors are a new failure mode (a structured question misrouted to document
  retrieval, or vice versa) — the evaluation harness needs to be scoped to catch this,
  and failure modes should be reported honestly, not hidden.
- This entry documents the target pattern; the document corpus generator, both
  retrieval legs, the routing agent, and the evaluation harness are not yet built.
  Status here is architecture-committed, not build-complete.

---

## DD-14. Single Fabric workspace at trial scope; workspace separation deferred

**Status:** Added 2026-07-13, reconciling documentation with the as-built trial tenant.

**Choice:** The entire build runs in one Fabric workspace (`pevc-dev`) — landing and
conformed lakehouses, all four conformed-layer notebooks, and (once built) the Gold
lakehouse, BI semantic model, and AI serving artefacts all live there together, instead
of the four-workspace split (`ws-ingestion-dev`, `ws-conformed-dev`, `ws-serving-bi-dev`,
`ws-serving-ai-dev`) that DD-10 and earlier `architecture.md`/`infrastructure/
workspace_layout.md` revisions described and named.

**Alternatives considered:**
- Workspace-per-layer, as DD-10 originally specified (RBAC and capacity isolation per
  ingestion/conformed/serving boundary).
- Two workspaces (raw + everything else) — DD-10's other rejected alternative, still
  more than this build uses.

**Rationale:**
DD-10's governance-boundary argument assumes multiple developers or teams whose access
needs to be scoped independently, and enough capacity budget to justify per-layer
allocation. Neither holds at trial scope: this is a single-maintainer build on one F2
trial capacity. A four-workspace split under those conditions adds Fabric admin
overhead (workspace creation, Git-connecting each one, cross-workspace shortcut wiring)
without a governance boundary it's actually enforcing — there's only one identity doing
all the work. Separation within `pevc-dev` is by **item** (lakehouse, notebook, future
semantic model) rather than by workspace; the data-quality boundary DD-10 cares about
(raw vs. conformed vs. serving) still exists, just as separate lakehouses inside one
workspace rather than separate workspaces.

**When workspace-per-layer is the right choice (not built here):** a team-operated
deployment where different people should have different access (data engineering
writes to conformed but not serving; BI developers publish reports but shouldn't see
landing), or a production capacity budget where ingestion, conformed-build, and serving
genuinely have different sizing/elasticity needs (see the capacity table this decision
leaves undisturbed in `infrastructure/workspace_layout.md`). DD-10's rationale is
unchanged for that context — it just isn't the context this portfolio build is in.

**Trade-offs accepted:**
- No workspace-level RBAC boundary between ingestion and conformed data at portfolio
  scope — acceptable because there's one identity operating the whole tenant. Item-level
  permissions within `pevc-dev` are the available substitute, not currently configured
  beyond the single owner (see `docs/governance.md` Layer 3/4).
- The documented four-workspace names (`ws-ingestion-dev` etc.) no longer describe the
  live tenant. Every doc that named them (`architecture.md`, `CLAUDE.md`,
  `infrastructure/workspace_layout.md`, `README.md`) is updated alongside this entry to
  say `pevc-dev` instead, so this doesn't become the next drift.

---

*Last updated: 2026-07-13. New decisions are appended; existing decisions are updated in place with revision notes when changed.*
