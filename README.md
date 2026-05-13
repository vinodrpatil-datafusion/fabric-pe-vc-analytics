# PE/VC Investment Analytics Platform on Microsoft Fabric

> A reference architecture and working portfolio project for institutional private equity and venture capital analytics, built on Microsoft Fabric.

**Status:** Active development. Architecture v1 complete; implementation in progress.
**Author:** Vinod Patil — Enterprise AI & Data Architect ([LinkedIn](https://www.linkedin.com/in/vinodrpatil/))
**Purpose:** Public portfolio artefact demonstrating Fabric-native architecture for institutional investment workflows.

---

## Why this project exists

Most public Microsoft Fabric content shows generic retail or telemetry use cases. Private market investment workflows — sourcing, screening, due diligence, portfolio monitoring — have a different shape: sparse data, relational density, point-in-time integrity, mixed structured and unstructured sources, and reliability requirements that come from capital being deployed against the outputs.

This project models that shape end-to-end on Fabric. It's not a production system. It's an architectural reference and a working build, intended to demonstrate:

- How OneLake, Lakehouse, Warehouse, and DirectLake compose for investment analytics workloads
- Where graph-aware modelling earns its place over flat relational structures
- How AI integration (Azure OpenAI) layers onto a Fabric data foundation without contaminating data quality
- How governance, lineage, and audit get designed in rather than retrofitted

## Scope and honesty statement

**What this is:**
- A Fabric-native architecture reference for PE/VC analytics
- Working implementation against a representative data model (DealRoom-style external feeds, synthetic internal deal data)
- Public design rationale and decision documentation

**What this is not:**
- A production system serving real institutional capital
- A multi-tenant SaaS platform
- A claim to sovereign-wealth-fund operating scale

The architectural patterns scale. The implementation here is sized for portfolio demonstration, not enterprise deployment.

## Architecture at a glance

```
External sources                    Fabric workspace structure
─────────────────                   ──────────────────────────
DealRoom (ndjson)        ─┐
S&P / Capital IQ-style   ─┤
news feeds               ─┤   ┌─────────────────────┐
                          ├──▶│ Ingestion workspace │  (Shortcuts, no copy)
Internal historical      ─┤   │  OneLake landing    │
deal data                ─┤   └──────────┬──────────┘
                          ┘              │
                                         ▼
                          ┌─────────────────────────────┐
                          │ Conformed workspace         │
                          │  Delta Lake (Lakehouse)     │
                          │  • Deterministic validation │
                          │  • Source reconciliation    │
                          │  • Bitemporal modelling     │
                          └──────────────┬──────────────┘
                                         │
                  ┌──────────────────────┼──────────────────────┐
                  ▼                      ▼                      ▼
        ┌─────────────────┐   ┌─────────────────────┐   ┌──────────────┐
        │ Serving — SQL   │   │ Serving — Semantic  │   │ Serving — AI │
        │ Warehouse       │   │ DirectLake → BI     │   │ AI Layer     │
        │ Analytical/     │   │ Power BI semantic   │   │ Azure OpenAI │
        │ aggregations    │   │ model               │   │ grounded     │
        └─────────────────┘   └─────────────────────┘   └──────────────┘

Governance plane: Purview-integrated lineage, sensitivity labels, workspace RBAC,
                  domain-organised (Investment Analytics domain)
```

See [`docs/architecture.md`](docs/architecture.md) for the full architecture with component-level rationale.

## Key design decisions

The full rationale is in [`docs/design_decisions.md`](docs/design_decisions.md). Headline choices:

| Decision | Choice | Why |
|---|---|---|
| Ingestion to landing | Shortcuts, not copies | Lineage clarity, no duplication, faster freshness |
| Conformed layer storage | Delta on Lakehouse | Schema evolution, time travel, AI workload friendliness |
| Analytical serving | Warehouse (T-SQL) | SQL optimiser, mature BI tooling, aggregation workloads |
| BI semantic layer | DirectLake → Power BI | No import refresh, sub-second on Delta, version-of-truth |
| Graph-aware modelling | Conformed layer with relationship tables, graph view via Spark | Investor/portfolio/co-investment queries are multi-hop |
| Temporal integrity | Bitemporal columns in Delta (effective_date, ingestion_date) | Investment data is point-in-time; "as-of" queries are first-class |
| AI integration | Azure OpenAI against pre-validated conformed data only | LLM never reasons over raw input; data quality enforced upstream |
| Governance | Workspace RBAC + Purview lineage + sensitivity labels | Audit substrate, not retrofit |

## Domain modelling

The conformed layer models the investment domain explicitly. Core entities:

- **Companies** — private and public, point-in-time attributes, sector taxonomy
- **Funding rounds** — with `announced_date`, `effective_date`, valuation, instrument type
- **Investors** — funds, vintages, fund managers, LP relationships where disclosed
- **Investments** — the n-to-n bridge: which investor backed which company in which round, with deal terms
- **People** — founders, board members, fund partners (with relationship history)
- **Deals (internal)** — pipeline stage, IC status, analyst owners
- **Documents** — memos, transcripts, news, with embeddings stored separately

The shape this enables: "Which funds backed B2B SaaS companies at Series B in 2022 that share board members with our existing portfolio?" is one query, not a workflow.

See [`docs/data_model.md`](docs/data_model.md) for the schema and the rationale behind each modelling choice.

## AI layer

Azure OpenAI is integrated against the conformed Delta layer, not the raw ingestion layer. The principle: the LLM reasons over validated, reconciled, source-attributed data — never over raw feeds.

Implementation pattern:

1. Structured retrieval against Delta tables (point-lookup or filtered scan)
2. Optional vector search against document embeddings for unstructured context
3. Prompt construction with explicit source attribution requirements
4. LLM call with structured output schema enforcement
5. Output validation against schema; failures route to human review

The accompanying agentic AI work — the AI Business Analyst Agent — lives in a [separate repository](https://github.com/vinodrpatil-datafusion/ai-business-analyst-agent) and demonstrates multi-agent decomposition patterns that would consume this platform.

## Repository structure

```
fabric-pe-vc-analytics/
├── README.md                     ← you are here
├── docs/
│   ├── architecture.md           Full architecture document
│   ├── design_decisions.md       Decision log with rationale
│   ├── data_model.md             Domain schema and modelling rationale
│   └── governance.md             RBAC, sensitivity, lineage approach
├── infrastructure/
│   ├── workspace_layout.md       Fabric workspace structure
│   └── deployment_pipelines.md   CI/CD approach (in progress)
├── pipelines/
│   ├── ingestion/                Fabric Data Pipelines (placeholder)
│   └── transformation/           Spark / Dataflow Gen2 logic
├── notebooks/
│   ├── 01_landing_validation.py  Schema validation against shortcuts
│   ├── 02_conformed_build.py     Delta build with reconciliation
│   └── 03_serving_views.sql      Warehouse views for analytics
└── semantic_model/
    └── investment_analytics.bim  Power BI semantic model (DirectLake)
```

## Roadmap

| Stage | Status | Notes |
|---|---|---|
| Architecture v1 | ✅ Complete | Documented in `docs/` |
| Workspace layout & domain setup | ✅ Complete | Trial tenant |
| Conformed Delta build with bitemporal modelling | 🔨 In progress | |
| DirectLake semantic model | 🔨 In progress | |
| Azure OpenAI integration layer | 📋 Planned | |
| Deployment pipelines (CI/CD via Git) | 📋 Planned | |
| Microsoft Purview lineage integration | 📋 Planned | |

## Related work

- **AI Business Analyst Agent** — Agentic AI architecture, complementary to this platform. [Repository](https://github.com/vinodrpatil-datafusion/ai-business-analyst-agent)
- **LGT Capital Partners** — Production VC analytics platform delivery (Azure Synapse / ADF / Cosmos DB / Azure OpenAI). Not public, summarised on [LinkedIn](https://www.linkedin.com/in/vinodrpatil/).

## Contact

This is part of an active practice in Enterprise AI & Data Architecture for financial services and regulated industries.

- **Email:** vinodrpatil@outlook.com
- **LinkedIn:** [linkedin.com/in/vinodrpatil](https://www.linkedin.com/in/vinodrpatil/)
- **Practice:** DataFusion Innovation

---

*Last updated: May 2026. This project is under active development; design documents may evolve.*
