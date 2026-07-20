# Deployment Pipelines

> **Status:** Implemented at portfolio scope (2026-07-20) — see DD-12's revisions in
> [`design_decisions.md`](../docs/design_decisions.md). **Git integration is the
> promotion mechanism** (PR merge `dev` → `test` → `main`); the Fabric deployment
> pipeline (`pevc-pipeline`) stays connected but its Deploy button is deliberately
> unused — see §1 and §3 for why running both as independent promotion paths into the
> same workspaces produced a real duplication risk on the first attempt.

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

Fabric items (notebooks, pipelines, semantic models, Lakehouse and Warehouse definitions) are tracked in Git and promoted across environment-scoped workspaces via **Git branch merges**.

**As-built (2026-07-20): Git integration is the promotion mechanism, not Fabric deployment pipelines.** The original design here treated Git integration and Fabric deployment pipelines as two coordinated mechanisms — Git for source control, deployment pipelines for workspace-to-workspace promotion. In practice, that combination is redundant at this build's scale and creates a real conflict: with `/fabric/pevc/` already holding full content on every branch (from the folder rename, done before `pevc-test`/`pevc-prod` existed), connecting each workspace's Git integration *alone* fully populated it — independently of the deployment pipeline. The pipeline's Compare view then showed that Git-synced content as unlinked to Dev's items, with a second copy ready to Deploy alongside it; using the Deploy button at that point would have created duplicates of every item, not a clean promotion.

So, one mechanism, not two:

1. **Git integration** — every workspace is connected to its own branch (`pevc-dev`↔`dev`, `pevc-test`↔`test`, `pevc-prod`↔`main`). A promotion is a PR merge between branches, and the target workspace's Git sync pulls the merge in. This *is* the promotion path.
2. **Fabric deployment pipeline** (`pevc-pipeline`) — stays connected, kept only for its Compare/diff view across environments if drift needs eyeballing. Its Deploy button is deliberately not part of the workflow.

**Caveat that doesn't go away either way:** Git sync carries item *definitions* (notebook code, semantic model schema, lakehouse structure) — not data. Delta table contents aren't tracked by Git. A promoted workspace needs its ingestion/conformed notebooks re-run there afterward to get real data; merging a branch alone only moves definitions.

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

- Git-connected to the `test` branch — this is how it receives promoted content (PR merge `dev` → `test`, then Git sync pulls it in).
- Also a stage in the `pevc-pipeline` deployment pipeline, but that pipeline's Deploy button is not used for promotion (see §1).
- Provisioned 2026-07-20; item definitions present via Git sync, no data populated yet (notebooks not re-run there).

### Prod — `pevc-prod`

- Git-connected to the `main` branch — receives promoted content via PR merge `test` → `main`.
- Also a stage in `pevc-pipeline`, same caveat as Test: not the promotion path.
- Provisioned 2026-07-20; item definitions present via Git sync, no data populated yet.

---

## 3. Promotion flow (as-built: Git-driven, no deployment-pipeline Deploy step)

```
Developer in pevc-dev workspace
        │
        │ commit
        ▼
Git: dev branch
        │
        │ pull request → review → merge
        ▼
Git: test branch
        │
        │ pevc-test's Git integration syncs the merge in
        │ (item definitions only -- re-run notebooks there for data)
        ▼
pevc-test workspace
        │
        │ integration testing, stakeholder sign-off
        ▼
Git: main branch (via PR from test)
        │
        │ pevc-prod's Git integration syncs the merge in
        ▼
pevc-prod workspace
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
branch at a shared folder path (`pevc-dev`↔`dev`, `pevc-test`↔`test`, `pevc-prod`↔`main`).
`pevc-test`/`pevc-prod` already hold item definitions via that initial Git sync.
`pevc-pipeline` (Fabric deployment pipeline) is connected but its Deploy button is
intentionally not used (§1). Still open:

- **A first real promotion via the actual Git-driven flow** — a PR merge `dev` → `test`
  with a genuine code change, confirming the sync-in and re-run-notebooks-for-data steps
  work end to end. Not yet exercised (the only promotion attempted so far was via the
  deployment pipeline's Deploy button, abandoned once it was clear it would duplicate
  content already present from the initial Git sync — see DD-12's second 2026-07-20
  revision).
- Automated evaluation runs on AI artefacts before promotion to Prod (`ai-integration/evaluate_agents.py`
  exists per WS5 Stage E — wiring it in as a promotion gate, e.g. a required PR check,
  is not yet done)
- Environment-specific data masking rules
- Environment-specific capacity/parameterisation (see §4's as-built note)
- Integration with Azure DevOps Pipelines for the non-Fabric items (Azure OpenAI deployments, supporting Azure resources)

---

*Last updated: 2026-07-20. This is a living document for an active build.*
