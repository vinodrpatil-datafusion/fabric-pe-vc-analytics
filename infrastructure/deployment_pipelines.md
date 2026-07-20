# Deployment Pipelines

> **Status:** Implemented at portfolio scope (2026-07-20) — see DD-12's revision in
> [`design_decisions.md`](../docs/design_decisions.md). Git integration and the Fabric
> deployment pipeline are both live across all three environments; first actual content
> promotion (Dev → Test) not yet exercised.

This document describes the CI/CD approach for promoting Fabric artefacts across environments: Dev → Test → Prod.

For the broader workspace structure, see [`workspace_layout.md`](workspace_layout.md). For the architectural context, see [`../docs/architecture.md`](../docs/architecture.md) Section 5.1.

**As-built note:** this document's original design (below) predates DD-14's collapse of
the four-layer workspace split (`ws-ingestion-dev` etc.) into one workspace,
`pevc-dev`. Applying DD-14's rationale across environment tiers too (single maintainer,
one identity, no governance boundary the split would actually enforce), the as-built
setup is **one workspace per tier, not per tier-per-layer**: `pevc-dev`, `pevc-test`,
`pevc-prod`, each holding the full item set. Where the sections below still describe
"one workspace per logical workspace" (§2) or name the four-workspace split, read that
as historical/aspirational design intent, not the live tenant — same caveat DD-14
already applies to `architecture.md` and `workspace_layout.md`.

---

## 1. Approach

Fabric items (notebooks, pipelines, semantic models, Lakehouse and Warehouse definitions) are tracked in Git and promoted across environment-scoped workspaces via **Fabric deployment pipelines**.

Two coordinated mechanisms:

1. **Git integration** — every workspace is connected to a Git branch. Developers commit changes from a workspace; changes flow to Git and are reviewed via pull request before merge.
2. **Fabric deployment pipelines** — promote items from one workspace to another (Dev → Test → Prod) with environment-specific parameterisation.

The combination gives source-controlled history with code review **and** environment-aware promotion.

---

## 2. Environment tiers (as-built, 2026-07-20)

Three tiers, one workspace each — not one workspace per logical layer within each tier
(see the as-built note above). All three share the trial capacity and the same Git
folder path, `/fabric/pevc/`, differing only by which branch each workspace tracks.

### Dev — `pevc-dev`

- Holds the full item set: landing/conformed/Gold lakehouses, all notebooks, the
  DirectLake semantic model, the Power BI report.
- Git-connected to the `dev` branch.
- Used for active development and architectural iteration.
- Capacity: shared trial capacity (also backing `pevc-test`/`pevc-prod`).

### Test — `pevc-test`

- Connected as a deployment pipeline stage from `pevc-dev`.
- Git-connected to the `test` branch.
- Promotion from Dev via the `pevc-pipeline` Fabric deployment pipeline.
- Provisioned 2026-07-20; no content promoted into it yet.

### Prod — `pevc-prod`

- Connected as a deployment pipeline stage from `pevc-test`.
- Git-connected to the `main` branch.
- Promotion from Test via the `pevc-pipeline` Fabric deployment pipeline.
- Provisioned 2026-07-20; no content promoted into it yet.

---

## 3. Promotion flow

```
Developer in Dev workspace
        │
        │ commit
        ▼
Git: dev branch
        │
        │ pull request → review → merge
        ▼
Git: test branch
        │
        │ Fabric deployment pipeline (Dev → Test)
        ▼
Test workspace
        │
        │ integration testing, stakeholder sign-off
        ▼
Git: main branch (via PR from test)
        │
        │ Fabric deployment pipeline (Test → Prod)
        ▼
Prod workspace
```

---

## 4. Environment parameterisation

Items are parameterised at promotion time:

| Parameter | Dev | Test | Prod |
|---|---|---|---|
| Source connection strings (DealRoom, etc.) | Dev/sample feed | Test/sandbox feed | Prod feed |
| Azure OpenAI deployment | Dev deployment | Test deployment | Prod deployment |
| Capacity assignment | F2 trial | Test capacity | Prod capacity |
| Sensitivity label scope | Relaxed | Production-like | Full enforcement |
| Audit retention | Short | Medium | Full |

Parameter values are managed in deployment pipeline rules, not in code.

**As-built note:** none of this table's parameterisation is configured yet — all three
workspaces currently share the same trial capacity (no separate Test/Prod capacity
exists to assign), and there's no real DealRoom/Capital IQ feed to vary by environment
(the platform runs on synthetic data throughout). This table remains the design intent
for when parameterisation is actually wired up.

---

## 5. Item-level promotion rules

Not all items promote on the same cadence:

- **Lakehouse definitions and schemas** — promoted together; schema changes require explicit migration steps.
- **Notebooks and pipelines** — promoted as a unit when the corresponding business logic is reviewed.
- **Semantic models** — promoted after schema changes have stabilised; semantic model changes are user-facing and require careful release coordination.
- **Prompt templates and structured output schemas** — versioned independently; changes to prompts that affect production AI responses are gated by evaluation runs (in progress).

---

## 6. Roadmap items

Provisioned (2026-07-20): all three workspaces exist, each Git-connected to its own
branch at a shared folder path, linked via the `pevc-pipeline` Fabric deployment
pipeline. Still open:

- A first actual content promotion (Dev → Test → Prod) — provisioning is done, but
  nothing has been promoted through the pipeline yet
- Automated evaluation runs on AI artefacts before promotion to Prod (`ai-integration/evaluate_agents.py`
  exists per WS5 Stage E — wiring it in as a promotion gate is not yet done)
- Environment-specific data masking rules
- Environment-specific capacity/parameterisation (see §4's as-built note)
- Integration with Azure DevOps Pipelines for the non-Fabric items (Azure OpenAI deployments, supporting Azure resources)

---

*Last updated: 2026-07-20. This is a living document for an active build.*
