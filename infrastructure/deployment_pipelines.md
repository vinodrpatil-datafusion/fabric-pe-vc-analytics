# Deployment Pipelines

> **Status:** Implemented and confirmed working end to end (2026-07-21) — see DD-12's
> revisions in [`design_decisions.md`](../docs/design_decisions.md). **Git integration
> is the promotion mechanism** (PR merge `dev` → `test` → `main`); the Fabric
> deployment pipeline (`pevc-pipeline`) stays connected but its Deploy button is
> deliberately unused — see §1 and §3 for why running both as independent promotion
> paths into the same workspaces produced a real duplication risk on the first
> attempt. A real change was promoted through both hops and verified via the Fabric
> REST API (§6). **Both `pevc-test` and `pevc-prod` are now fully populated, their
> notebooks run cleanly against their own independent data, and both Power BI reports
> load correctly** — getting there required fixing four environment-binding gaps Git
> sync alone didn't handle (stale lakehouse bindings, hardcoded absolute paths, a
> DirectLake semantic model still pointing at `pevc-dev`, a stale SQL analytics
> endpoint metadata cache — §6), now automated end to end by
> `fixup_environment_bindings.py` (§7) and validated against both live environments —
> plus uploading landing data itself, a separate, expected, non-binding step neither
> Git sync nor the fixup script is meant to cover.

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

**Confirmed working end to end (2026-07-20).** A real change (markdown added to
`05_gold_star_schema`, committed via `pevc-dev`'s Source Control panel) was promoted
`dev` → `test` → `main` via two PR merges (#1, #2), with each of `pevc-test`/`pevc-prod`
pulling the merge in through their own Git sync — no deployment-pipeline Deploy button
involved. Verified independently via the Fabric REST API, not just visual inspection:
`GET /v1/workspaces/{id}/git/status` for both `pevc-test` and `pevc-prod` returned
`workspaceHead == remoteCommitHash` with `changes: []`, matching each branch's actual
HEAD commit.

**The "definitions only, not data" caveat is also confirmed, not just assumed.**
Listing `pevc-test`'s `landing_lakehouse` OneLake path
(`Tables/Tables/dbo` via the ADLS Gen2 API) shows the schema-enabled-lakehouse
scaffolding present but **zero actual table folders underneath** — the Git-synced
lakehouse is a structurally-correct empty shell. Getting real data into a promoted
workspace requires re-running the ingestion/conformed notebooks there.

**`pevc-test` fully populated and verified (2026-07-21).** Running the notebooks
there surfaced three items beyond the Git sync itself, found and fixed before any
data flowed — two real environment-binding gaps, plus the expected landing-data
upload (not itself a binding gap, but still a step Git sync doesn't cover):

1. **Lakehouse metadata binding** — all 5 promoted notebooks still had their default
   (and secondary) lakehouse attachment bound to `pevc-dev`'s actual workspace/lakehouse
   IDs, despite physically living in `pevc-test`. Confirmed via `getDefinition` on each
   notebook (the `dependencies.lakehouse` metadata block), fixed by manually re-attaching
   each notebook's lakehouse(s) to `pevc-test`'s own in the portal, reverified via the
   same API call afterward. Left uncommitted (not pushed to `test`) deliberately —
   committing an environment-specific binding would conflict with `dev`'s version of the
   same lines on the next real promotion.
2. **Hardcoded absolute paths in code, independent of the metadata binding** —
   `01_schema_validation`'s `LANDING_FILES` and the reference-file path in
   `02_reconciliation`/`03_bitemporal_load`/`04_data_quality_assertions` are plain
   `abfss://<workspace-id>@onelake.../<lakehouse-id>/...` string literals, still pointing
   at `pevc-dev` even after the metadata fix. `05_gold_star_schema` has no hardcoded
   paths (reads only via `spark.read.table` through its lakehouse attachment). Fixed by
   editing the 4 literals to `pevc-test`'s IDs, reverified via `getDefinition`. Same
   "leave uncommitted" reasoning as the lakehouse binding.
3. Landing data itself also needed uploading (`pevc-test`'s `landing_lakehouse` started
   with zero source files) — 18 files across `capitaliq`/`dealroom`/`internal`(3 of 5
   files only)/`reference`, matching `pevc-dev`'s real structure exactly, verified via
   OneLake directory listing before running anything.

With all three fixed, `01`→`05` ran cleanly against `pevc-test`'s own, independent
storage (verified via OneLake table listings after each step, not just "the notebook
said success"): **conformed layer's `dq_assertions_report` — all 45 checks PASS**;
**Gold layer's `gold_dq_assertions_report` — 6 PASS, 1 WARN**, the identical known
generator-calibration artifact already documented for `pevc-dev` (funding rounds
closing before company `founded_date`) — not a new problem, a consistent match to the
known-good baseline.

**`pevc-prod` repeated the same three fixes and got the same clean result.** One
miss on the first pass: `05_gold_star_schema`'s lakehouse binding was left pointing at
`pevc-dev` — easy to miss since it's the one notebook with no hardcoded path to also
edit, so nothing else prompted a return to it. Caught by re-running the same
`getDefinition` verification, fixed the same way. Once all three fixes were confirmed,
`01`→`05` produced an identical result to `pevc-test`: conformed layer 45/45 PASS,
Gold layer 6 PASS/1 WARN (same calibration artifact).

**Verification lesson, worth remembering if this OneLake-listing technique gets reused:**
checking `pevc-prod`'s Gold DQ report this way first showed what looked like 14 rows
(every check duplicated) instead of 7. That wasn't a real bug — `05_gold_star_schema`
had been run twice, and `.mode("overwrite")` on Delta tables doesn't delete old
physical parquet files immediately, it marks them removed in `_delta_log` and leaves
them until vacuumed. A naive "list every `.parquet` file in the table folder" query
picks up both the superseded and current files. The fix is to read `_delta_log`'s
`add`/`remove` actions (or just use a real Spark/SQL-endpoint read) to know which
files are actually active, rather than assuming every file present is live.

**A fourth gap, found only once someone actually opened the Power BI report:**
`pevc-semantic-model`'s DirectLake source is not controlled by anything a notebook's
lakehouse-explorer-style rebinding touches. Its `definition/expressions.tmdl` hardcodes
an `AzureStorage.DataLake(...)` connection string with `pevc-dev`'s exact workspace ID
and `gold_lakehouse` ID, baked in at whatever point the model was originally created —
Git-syncing the model into `pevc-test`/`pevc-prod` carried that string over unchanged.
Symptom: *"table 'gold_fact_investment' is not refreshed and fallback to DirectQuery is
disabled for this semantic model."* No portal UI path was found to repoint a DirectLake
model's source lakehouse ("Edit tables" only includes/excludes tables from whatever
source is already bound; "Transform data" wasn't tried since the fix below worked) — a
targeted fix was applied via the Fabric REST API's `updateDefinition`, editing only the
one `expressions.tmdl` line (same mechanism Git integration itself uses to write these
files, not a workaround), leaving every table/relationship/measure untouched. Verified
by re-fetching the definition before touching anything further.

**A fifth, related gap:** even after the DirectLake source was corrected, `pevc-test`'s
report failed differently — *"Unable to load a query that produces no tables,"* and the
model's "Edit tables" dialog couldn't enumerate any tables at all. The underlying Delta
tables were confirmed still present via OneLake; the actual cause was the Lakehouse's
**SQL analytics endpoint metadata cache** lagging behind the fresh Spark write from
`05_gold_star_schema` — DirectLake's table discovery goes through that endpoint, not
directly through OneLake. Fixed via the Fabric REST API's
`POST /v1/workspaces/{id}/sqlEndpoints/{id}/refreshMetadata`, confirmed by the returned
`lastSuccessfulSyncDateTime` jumping to the current time for all 5 tables. Both reports
loaded correctly after this.

Still open:

- Automated evaluation runs on AI artefacts before promotion to Prod (`ai-integration/evaluate_agents.py`
  exists per WS5 Stage E — wiring it in as a promotion gate, e.g. a required PR check,
  is not yet done)
- Environment-specific data masking rules
- Environment-specific capacity/parameterisation (see §4's as-built note)
- Integration with Azure DevOps Pipelines for the non-Fabric items (Azure OpenAI deployments, supporting Azure resources)
- ~~A more durable fix than manual per-environment rebinding~~ — **done:**
  `fixup_environment_bindings.py` (below)

## 7. `fixup_environment_bindings.py`

Automates all four environment-binding fixes above (not the landing-data upload —
see "What it doesn't do" below), given a target environment name. Same
mechanism as Git integration itself — every fix is a `getDefinition`/
`updateDefinition` REST call, not a workaround. Driven by name lookups
(workspace, lakehouse, notebook, semantic model names), not hardcoded GUIDs,
so it's reusable if a third non-Dev environment is ever added.

**How it works:** every one of the four binding gaps found by hand turned out to be
the same source-workspace/lakehouse GUIDs appearing as plain substrings in
TMDL/notebook text — a notebook's `dependencies.lakehouse` metadata block, a
hardcoded `abfss://` path, the semantic model's `AzureStorage.DataLake(...)`
connection string. So the fix is one blanket old-GUID → new-GUID
substitution map, applied to just the relevant text parts of each item's
definition (leaving tables, relationships, measures, other code cells
untouched), pushed back only if something actually changed. Also triggers a
SQL analytics endpoint metadata refresh for all three lakehouses regardless
(cheap, idempotent, and was the fifth gap).

**What it doesn't do**: upload landing data into a fresh `landing_lakehouse`,
or run the conformed/Gold notebooks — those stay manual (lower-frequency,
closer to one-time-per-environment concerns). This script only fixes the
bindings that would otherwise make those manual runs silently target the
wrong environment's storage.

**Validated (2026-07-21)**: run against both `pevc-test` and `pevc-prod`
(both already correctly bound from the manual fixes earlier the same day) —
correctly reported "no source-environment references found" for every
notebook and the semantic model in both environments, and safely re-triggered
the SQL endpoint refresh regardless. Confirms the substitution logic matches
reality without needing to break a binding first just to test the fix.

```bash
cd infrastructure
pip install -r requirements.txt
az login   # the identity with RBAC on the target workspace
python fixup_environment_bindings.py --target pevc-test
python fixup_environment_bindings.py --target pevc-prod --yes   # --yes skips the confirmation prompt
```

---

*Last updated: 2026-07-21. This is a living document for an active build.*
