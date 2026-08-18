# Changelog

Build narrative for the PE/VC Investment Analytics Platform. Entries are grouped by
workstream (WS1–WS5) and dated by the day the work landed on `main`.

This log records what was built **and what was found broken**, including bugs caught in
live-tenant validation. Those entries stay in — a reference architecture that never
records a wrong answer isn't documenting a real build.

Decision references (`DD-nn`) point at [`docs/design_decisions.md`](docs/design_decisions.md).

---

## 2026-07-22 — WS5 evaluation finalised

- `ai-integration/EVALUATION.md` published: methodology plus results, scored against
  known-correct oracles rather than an LLM judge.
- Structured leg **6/6 grounded**. Document leg **4/6 grounded**, citation-accuracy
  **4/5** (of cases returning any citation), annotation coverage **5/6**.
- Groundedness, citation-accuracy, and annotation coverage reported as three separate
  numbers — a missing Foundry `file_citation` annotation is a plumbing gap, not a
  groundedness failure, and conflating them would hide which one occurred.
- Run-to-run variance disclosed rather than smoothed: an earlier run (2026-07-20,
  reproduced twice) scored 5/6 on the document leg. Both runs are recorded.
- Full-repo alignment pass — code/doc drift corrected beyond markdown wording.

## 2026-07-21 — Deployment pipelines verified end to end

- `pevc-dev` → `pevc-test` → `pevc-prod` fully populated and independently verified:
  data, notebooks, semantic model, and reports all working in Test and Prod.
- Six environment-binding fixes required after each Git sync were automated in
  [`infrastructure/fixup_environment_bindings.py`](infrastructure/fixup_environment_bindings.py)
  — including two found late (semantic model and SQL endpoint bindings).

## 2026-07-20 — WS5 AI layer, Stages C–E · promotion mechanism settled

- **Stage C** — `structured_agent.py`: one function-calling tool per `docs/measures.md`
  entry, each backed by a fixed parameterized DAX query against `pevc-semantic-model`.
  The LLM selects a tool and fills filter arguments; it never writes DAX.
  - Fix: `sector_group` constrained to a **live-fetched** JSON Schema `enum`. A hardcoded
    list let the model pick plausible-but-wrong values (`'Tech'`, `'FinTech'`) that
    returned empty results indistinguishable from a genuinely blank measure.
  - Fix: single tool-call round-trip replaced with a capped loop (`MAX_TOOL_ROUNDS`) —
    multi-step questions ("which sector performed best") need chained calls.
  - Finding: the LLM call and the DAX query are different resources needing RBAC on
    **two separate permission surfaces** (Azure IAM *and* a project-level Foundry grant).
    The IAM grant alone still 401'd.
- **Stage D** — `fusion_agent.py`: routes each question structured / document / hybrid via
  a single forced-choice tool call, kept deliberately separate from a
  one-LLM-with-both-tools design (DD-13 rejected that: opaque routing, and Stage E needs
  per-leg scores, not blended ones). Per-leg degradation is graceful.
  - Fix: the document leg's first design (`vector_stores.search()`) 404'd against this
    project's `ManagedAzureSearch`-backed Knowledge store — switched to the Responses
    API's built-in `file_search`.
- **Stage E** — `evaluate_agents.py`: oracle-based evaluation harness (see 2026-07-22).
- **DD-12 revised twice**: deployment pipelines provisioned, then the promotion mechanism
  changed to **Git-driven** (PR merge `dev`→`test`→`main`). Running Fabric's Deploy button
  and Git sync in parallel produced a real duplication risk on the first attempt.
- Fabric Git folder renamed `fabric/pevc-dev/` → `fabric/pevc/` so all three environment
  branches share one path.

## 2026-07-19 — WS5 Stage B: corpus indexed

- `index_corpus.py` indexed **1,568/1,568** LP documents into an Azure AI Foundry vector
  store; verified live at 0 failed via `verify_corpus.py`.
- Finding: `azure-ai-projects==2.3.0` moved vector-store operations off
  `AIProjectClient.agents` onto the OpenAI-compatible client.
- Finding: one file's server-side processing stalled indefinitely and hung a full run for
  over an hour. Replaced the SDK's unbounded `upload_and_poll` with a self-driven poll
  loop, a 60s timeout, and retry-with-cleanup.
- Finding: the Foundry portal's "Failed files" card can show stale counts. Trust the API.

## 2026-07-15 — Measure contract · WS5 pre-gate · DD-17

- [`docs/measures.md`](docs/measures.md) added: LP meaning, definition, valid grain, and
  caveats for all 7 measures — plus why **DPI is deliberately absent**.
- **DD-13 revised**: the native Fabric Data Agent is blocked on trial capacity (SKU-type
  gate, not capacity units). The structured leg was re-platformed as a custom
  function-calling agent rather than designed around an untested assumption.
- **DD-17**: LP document corpus schema. Corpus is **templated, not LLM-seeded**, to keep
  `seed=42` reproducibility and avoid fabricated numeric precision — which is also what
  makes oracle-based evaluation possible at all.

## 2026-07-14 — WS4: semantic model, report, and a 1,000,000x bug

- DirectLake semantic model `pevc-semantic-model` built: 4 Gold tables, relationships
  (company/investor/effective_date active, exit_date inactive), 5 headline + 2 supporting
  measures.
- `LP Portfolio Performance` report page built — KPI row, vintage and sector tables,
  sector-concentration chart.
- **DD-16**: IRR-proxy method (MOIC annualisation), documented as a proxy because the
  dataset carries no periodic fair-value marks.
- **Bug found in live validation and fixed:** generator dollar amounts were understated
  by ~1,000,000x — `stage_scale`/lognormal params in `canonical.py` were calibrated in
  $ millions for readability and never converted to currency units, violating
  `data_model.md`'s stated contract. Surfaced by `Total Invested` reading ~$2.2K instead
  of a plausible portfolio total. Ratio measures (MOIC, IRR, concentration) were
  unaffected — the missing scale factor cancels — which is exactly why it survived to
  the BI layer. Fixed, `sample-data/` regenerated, pipeline 01→05 re-run, report
  re-verified.
- Bitemporal-envelope and Gold schema-drift bugs found in the first live Fabric run.

## 2026-07-13 — WS3: Gold star schema · as-built reconciled with docs

- **DD-15**: Gold grain settled — one fact (`fact_investment`) + three dimensions
  (`dim_company`, `dim_investor` as Type-2 SCD, `dim_date`). No fund-performance-snapshot
  fact; NAV and vintage rollups become DAX measures with an explicit proxy caveat.
- `notebooks/05_gold_star_schema.ipynb` executed and certified against live `pevc-dev`.
- **DD-14** documented: the trial tenant runs one workspace per environment tier, not the
  workspace-per-layer target (DD-10). Docs reconciled to say so rather than describing an
  architecture that wasn't provisioned.
- **DD-05** reconciled: Fabric Warehouse deliberately deferred; analytical SQL is via the
  Lakehouse SQL endpoint, with a stated "when you'd add it back."
- Fix: notebook 01 resolved `LANDING_FILES` against the wrong lakehouse.

## 2026-06-15 — WS2: conformed layer

- Four PySpark notebooks: schema validation (with quarantine) → multi-source
  reconciliation → bitemporal load → data-quality assertions.
- Reconciliation **surfaces conflicts rather than silently picking winners**
  (`reconciliation_status` ∈ `clean` / `conflict_resolved` / `conflict_flagged`).
- Scored **1.000/1.000** against the synthetic conflict oracle — detecting genuine
  disputes *and* correctly not flagging coverage gaps.

## 2026-06-11 — WS1: synthetic data generator

- `data-generator/` package: canonical oracle → per-source projections with controlled
  conflicts → landing feeds. Curated PE/VC name banks, no Faker dependency.
- Rebuilt against `data_model.md` after v1 drifted from the documented schema.
- `expected_conflicts` ledger added, resolving the conflation of *genuine dispute* with
  *coverage gap* — the distinction WS2 is scored on.

## 2026-05-13 — Architecture v1

- Initial architecture, data model, governance, and the numbered decision log.

---

## Known open items

| Item | Status |
|---|---|
| Microsoft Purview lineage integration | Designed (`docs/governance.md`), not wired up in the trial tenant |
| Fabric Warehouse | Deliberately deferred (DD-05), with documented re-entry criteria |
| OneLake shortcuts for landing | Documented (DD-02); this build uploads Parquet directly — no external ADLS Gen2 source exists to shortcut to |
| Workspace-per-layer RBAC | Documented target (DD-10); trial scope uses item separation within one workspace per tier (DD-14) |
| Multi-tenancy | Documented extension path, not built (single-tenant by design) |
| Document-leg retrieval ranking | Known weakness on near-duplicate `quarterly_letter` documents — recorded, not tuned away |
