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

Warehouse remains the right choice for analytical serving (see DD-05), but the conformed layer where data quality and bitemporal modelling are enforced wants Delta's flexibility.

**Trade-offs accepted:**
- Delta on Lakehouse is read via SQL endpoint or Spark; the SQL endpoint has fewer optimiser features than Warehouse. Mitigated by serving analytical workloads through Warehouse via shortcut from the conformed Lakehouse.

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
- Query complexity — bitemporal queries are non-trivial. Mitigated by encapsulating the common "as-of-date" patterns in Warehouse views and DAX measures, so analysts don't write the bitemporal logic each time.

---

## DD-05. Warehouse for analytical serving, Lakehouse SQL endpoint not used for analyst queries

**Choice:** Analytical SQL workloads (analyst ad-hoc, complex aggregations, BI back-end where DirectLake doesn't apply) served from Fabric Warehouse, not from the Lakehouse SQL endpoint.

**Alternatives considered:**
- Lakehouse SQL endpoint as the only SQL surface
- Hybrid — some workloads to each

**Rationale:**
Warehouse has the more mature SQL optimiser for analytical workloads — complex joins, window functions, multi-fact aggregations. Lakehouse SQL endpoint works for read-only Delta queries with simpler shapes, but the analyst query patterns here lean analytical-heavy.

The conformed Lakehouse remains the storage substrate; Warehouse reads from it via OneLake shortcut. Single copy of data, two SQL surfaces with different optimisation characteristics.

**Trade-offs accepted:**
- Two SQL engines for the team to understand. Mitigated by the convention: Warehouse for analytics, Lakehouse SQL endpoint reserved for ETL inspection and lightweight notebooks.

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

**Choice:** Ingestion, conformed, and serving in separate Fabric workspaces with explicit RBAC and shortcut-based read access.

**Alternatives considered:**
- Single workspace with folder-level organisation
- Two workspaces (raw + everything else)

**Rationale:**
Workspaces in Fabric are the unit of RBAC, capacity allocation, and Git source control. Aligning them with the data quality boundary (raw, conformed, serving) gives a clean mapping from organisational governance to technical enforcement. A developer who has access to serving workspaces does not automatically have access to landing workspaces; promotion paths are explicit.

**Trade-offs accepted:**
- More workspaces to manage. Acceptable; the operational overhead is small relative to the governance value.
- Cross-workspace dependencies need to be designed (shortcut paths, deployment pipeline ordering). This is by design — making the dependencies explicit is the point.

---

## DD-11. Microsoft Purview for lineage, not custom

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

*Last updated: May 2026. New decisions are appended; existing decisions are updated in place with revision notes when changed.*
