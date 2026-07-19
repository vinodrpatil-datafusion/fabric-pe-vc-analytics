# ai-integration

WS5: the fusion agent (DD-13) — structured retrieval over the Gold semantic model and
document retrieval over the synthetic LP corpus (DD-17), composed by a routing layer.

See [`../docs/design_decisions.md`](../docs/design_decisions.md) DD-13 for the pattern
and its 2026-07-15 revision (native Fabric Data Agent is blocked on trial capacity —
the structured leg is a custom function-calling agent instead, not the native item).

## Stages

| Stage | Does | Status |
|---|---|---|
| A | Synthetic LP document corpus (`data-generator/pevc_generator/lp_documents.py`) | Complete — see DD-17 |
| B | Index the corpus in Azure AI Foundry (`index_corpus.py`) | Complete — 1,568/1,568 files verified completed, 0 failed (`verify_corpus.py`) |
| C | Custom function-calling agent over the Gold schema | Not started |
| D | Fusion agent — routes structured / document / hybrid questions to both legs | Not started |
| E | Evaluation harness — groundedness + citation-accuracy, scored per leg | Not started |

## Setup

```bash
cd ai-integration
pip install -r requirements.txt
cp .env.example .env      # fill in your Azure AI Foundry project endpoint
python index_corpus.py    # Stage B
python verify_corpus.py   # confirm live per-file status directly via the API --
                          # the Foundry portal's "Failed files" card can show
                          # stale/orphaned counts (see index_corpus.py's docstring)
```

`.env` is git-ignored — never commit real endpoints/keys, same placeholder discipline
the notebooks use for `REFERENCE_FILES` ABFS paths.

`cleanup_orphaned_failed.py` is a one-off utility: if a retry ever leaves a
failed attachment alongside a since-succeeded one (index_corpus.py now
cleans these up itself, but the script is kept for re-verification / manual
recovery), it deletes any `failed` attachment that has a `completed`
counterpart for the same `lp_document_id`.

## How `index_corpus.py` works

Takes the `lp_documents` landing table (Stage A output, DD-17) and makes it
searchable by the document-retrieval leg of the fusion agent (`file_search`
over a Foundry vector store). Four steps:

1. **Load** — reads `sample-data/landing/internal/lp_documents.parquet` with
   pandas (falls back to `.csv` if parquet isn't present).
2. **Materialize** — writes one small `.txt` file per row into a temp
   directory, named `<lp_document_id>.txt`. The ID is also stated inside the
   text itself, so a retrieved chunk stays traceable back to
   `lp_document_manifest` (§1.10 of `data_model.md`) even without the
   filename — needed for citation-accuracy scoring in Stage E.
3. **Get-or-create the vector store** — looks up a store named
   `LP_VECTOR_STORE_NAME` (default `pevc-lp-documents`). If one already
   exists with `file_counts.completed >= len(corpus)`, the run is skipped
   entirely (idempotent no-op). Otherwise a fresh store is created — the
   check deliberately uses `completed`, not `total`, so a store left with
   lingering failures from an interrupted prior run isn't mistaken for done.
4. **Upload each file** — for every document: upload the file, attach it to
   the vector store, then poll for a terminal status ourselves (not the SDK's
   built-in `upload_and_poll`, which has no timeout — see caveat below) up to
   `POLL_TIMEOUT_SECONDS` (60s). If it doesn't reach `completed` in that
   window, or comes back `failed`, the attachment is deleted and the whole
   upload is retried, up to `MAX_UPLOAD_ATTEMPTS` (3) times. A file still not
   `completed` after all attempts is reported by `lp_document_id` in the
   final summary, and the script exits non-zero.

**Caveats learned running this against a live (trial-capacity) Foundry
project**, in case they resurface:

- The `azure-ai-projects` SDK's shape shifts across versions. As of
  `azure-ai-projects==2.3.0`, vector-store/file operations are *not* under
  `AIProjectClient.agents` (that's a different, session/version-based
  resource model in this version) — they're on the OpenAI-compatible client
  from `AIProjectClient.get_openai_client()`, using the standard `openai`
  SDK's `vector_stores` / `vector_stores.files` surface. If this breaks
  again on a future SDK bump, `pip show azure-ai-projects` and re-inspect
  `dir(...)` before assuming the whole approach is wrong.
- A single file's server-side processing once stalled indefinitely and hung
  an entire ~1,568-file run for over an hour (process alive, 0% CPU, one
  idle connection) — hence the self-driven poll loop with a timeout instead
  of trusting the SDK's unbounded one.
- The Foundry portal's vector-store summary card ("Failed files: N") can
  disagree with live status — in one run it kept showing stale counts after
  the underlying files had already succeeded, and separately, genuine
  orphaned failed attachments (see `cleanup_orphaned_failed.py`) didn't show
  up as a portal-vs-reality inconsistency until queried directly via the
  API. Trust `verify_corpus.py`'s live query over the portal card.
- Idempotency here is coarse (all-or-nothing), not per-file — rerunning
  against a vector store that's short some files re-uploads *every* file,
  which would create duplicates for the ones already completed. Delete the
  vector store in the portal first if you want a clean rebuild rather than
  rerunning on top of a partial one.

## Why a separate folder from `data-generator/`

`data-generator/` produces synthetic data with no external dependencies (pure Python,
deterministic, `seed=42`). This folder calls out to a real Azure AI Foundry project —
different dependency profile, different secrets-handling needs, and arguably a
different audience (whoever's driving the AI integration, not necessarily whoever's
tuning conflict rates). Kept separate rather than folded into `data-generator/`.
