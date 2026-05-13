# Deployment Pipelines

> **Status:** In progress. This document captures the design; implementation is partial at portfolio scope.

This document describes the CI/CD approach for promoting Fabric artefacts across environments: Dev → Test → Prod.

For the broader workspace structure, see [`workspace_layout.md`](workspace_layout.md). For the architectural context, see [`../docs/architecture.md`](../docs/architecture.md) Section 5.1.

---

## 1. Approach

Fabric items (notebooks, pipelines, semantic models, Lakehouse and Warehouse definitions) are tracked in Git and promoted across environment-scoped workspaces via **Fabric deployment pipelines**.

Two coordinated mechanisms:

1. **Git integration** — every workspace is connected to a Git branch. Developers commit changes from a workspace; changes flow to Git and are reviewed via pull request before merge.
2. **Fabric deployment pipelines** — promote items from one workspace to another (Dev → Test → Prod) with environment-specific parameterisation.

The combination gives source-controlled history with code review **and** environment-aware promotion.

---

## 2. Environment tiers

Three tiers planned. At portfolio scope, only Dev is fully realised.

### Dev

- One workspace per logical workspace (ingestion, conformed, serving-warehouse, serving-bi, serving-ai).
- Git-connected to `dev` branch.
- Used for active development and architectural iteration.
- Capacity: F2 (trial).

### Test

- Mirror of Dev workspace layout.
- Git-connected to `test` branch.
- Promotion from Dev via deployment pipeline.
- Used for integration testing and stakeholder validation before production release.

### Prod

- Mirror of Dev/Test workspace layout.
- Git-connected to `main` branch.
- Promotion from Test via deployment pipeline.
- Production capacity allocation (sized per Section 5 of `workspace_layout.md`).

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

---

## 5. Item-level promotion rules

Not all items promote on the same cadence:

- **Lakehouse definitions and schemas** — promoted together; schema changes require explicit migration steps.
- **Notebooks and pipelines** — promoted as a unit when the corresponding business logic is reviewed.
- **Semantic models** — promoted after schema changes have stabilised; semantic model changes are user-facing and require careful release coordination.
- **Prompt templates and structured output schemas** — versioned independently; changes to prompts that affect production AI responses are gated by evaluation runs (in progress).

---

## 6. Roadmap items

This implementation is in progress at portfolio scope. The following are planned:

- Full Test workspace realisation
- Automated evaluation runs on AI artefacts before promotion to Prod
- Environment-specific data masking rules
- Integration with Azure DevOps Pipelines for the non-Fabric items (Azure OpenAI deployments, supporting Azure resources)

---

*Last updated: May 2026. This is a living document for an active build.*
