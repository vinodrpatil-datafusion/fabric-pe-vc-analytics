# ai-integration

WS5: the fusion agent (DD-13) — structured retrieval over the Gold semantic model and
document retrieval over the synthetic LP corpus (DD-17), composed by a routing layer.

See [`../docs/design_decisions.md`](../docs/design_decisions.md) DD-13 for the pattern
and its 2026-07-15 revision (native Fabric Data Agent is blocked on trial capacity —
the structured leg is a custom function-calling agent instead, not the native item).
See [`EVALUATION.md`](EVALUATION.md) for the full evaluation results and methodology.

## Stages

| Stage | Does | Status |
|---|---|---|
| A | Synthetic LP document corpus (`data-generator/pevc_generator/lp_documents.py`) | Complete — see DD-17 |
| B | Index the corpus in Azure AI Foundry (`index_corpus.py`) | Complete — 1,568/1,568 files verified completed, 0 failed (`verify_corpus.py`) |
| C | Custom function-calling agent over the Gold schema (`structured_agent.py`) | Complete — validated against live `pevc-semantic-model` across single-measure, sector-filtered, and multi-step comparison questions |
| D | Fusion agent — routes structured / document / hybrid questions to both legs (`fusion_agent.py`) | Complete — structured/document/hybrid routing, both legs, and hybrid synthesis validated against live data |
| E | Evaluation harness — groundedness + citation-accuracy, scored per leg (`evaluate_agents.py`) | Complete — structured leg 6/6 grounded; document leg 5/6 grounded, 5/6 citation-accuracy (see finding below) |

## Setup

```bash
cd ai-integration
pip install -r requirements.txt
cp .env.example .env      # fill in your Azure AI Foundry project endpoint
python index_corpus.py    # Stage B
python verify_corpus.py   # confirm live per-file status directly via the API --
                          # the Foundry portal's "Failed files" card can show
                          # stale/orphaned counts (see index_corpus.py's docstring)
python structured_agent.py "What's the MOIC for the 2022 vintage?"   # Stage C
python document_agent.py "What have LP letters said about portfolio risk?"   # Stage D leg
python fusion_agent.py "How did FinTech perform, and what did LPs say about it?"   # Stage D
python evaluate_agents.py   # Stage E
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

## How `structured_agent.py` works

Answers NL2metric questions (MOIC, IRR proxy, NAV proxy, sector concentration,
vintage performance) over `pevc-semantic-model` — the structured leg of the
fusion agent (DD-13, re-platformed off the native Fabric Data Agent per its
2026-07-15 revision, since that's blocked on trial capacity).

**Deterministic-core, LLM-picks-not-writes.** One tool function per
`docs/measures.md` entry, each backed by a fixed, parameterized DAX query.
The LLM never writes DAX itself — it only selects a tool and fills
`vintage_year`/`sector_group`/`as_of_date` arguments. `sector_group` is
constrained to a live-fetched JSON Schema `enum` (queried once at startup via
`VALUES(gold_dim_company[sector_group])`), not a hardcoded list — the
generator's full taxonomy has 8 groups but which ones actually have companies
at a given seed/scale varies, and a guessed static list let the model pick
plausible-sounding wrong values (`'Tech'`, `'FinTech'`) that silently
returned empty results indistinguishable from a genuinely blank measure.

**Multi-step tool-calling loop**, not a single round-trip: a question like
"which sector performed best" needs `get_sector_concentration` (to learn
which sectors exist) *then* `get_moic`/`get_irr_proxy` per sector before any
final text answer — capped at `MAX_TOOL_ROUNDS` (6) to avoid a runaway loop.

**Two resources, one identity.** The LLM call (Azure AI Foundry) and the DAX
query (Fabric/Power BI `executeQueries`) are different resources that
initially needed two different accounts — confirmed by hitting a real 403
testing cross-identity access. Once one account has RBAC on both (Fabric
workspace access *and* the Foundry resource's "Cognitive Services OpenAI
User" role — the latter is a separate grant from whatever role already
allowed `index_corpus.py`'s vector-store calls to work, and in this project
turned out to need adding at *both* the Azure IAM level and a project-level
Foundry "Users"/Management Center list, two distinct permission surfaces),
one `InteractiveBrowserCredential` requests tokens for both scopes. Set
`AGENT_LOGIN_HINT` in `.env` to that account — never hardcode a real account
name in this script or its docs, only in the git-ignored `.env`. Token
caching is persistent (macOS Keychain via `TokenCachePersistenceOptions`),
so the browser prompt appears once, not on every run.

Auth and env-loading now live in `agent_common.py` (`build_context()`),
shared with `document_agent.py` and `fusion_agent.py` so a run authenticates
once regardless of how many legs it touches — `structured_agent.py` is still
fully runnable standalone; `answer_structured()` is also what
`fusion_agent.py` calls when it routes a question here.

**Transient LLM-call failures retry automatically** — `agent_common.py`'s
`call_with_retry()` wraps every `chat.completions.create`/`responses.create`
call across all three scripts (`MAX_LLM_CALL_ATTEMPTS`, default 3). Seen in
practice: a `401 PermissionDenied` from a fully-permissioned, working account
that resolved itself on a bare retry seconds later — same class of
backend flakiness as `index_corpus.py`'s upload retries, not a real
permissions regression. A genuinely permanent failure still surfaces, just
after the retries instead of on the first attempt.

## How `document_agent.py` works

The document-retrieval leg, over the Stage B corpus (`pevc-lp-documents`).
Uses the OpenAI **Responses API**'s built-in `file_search` tool
(`responses.create(..., tools=[{"type": "file_search", "vector_store_ids": [...]}])`)
— retrieval and grounded narration happen in one call, citations come back
as `file_citation` annotations on the output.

**Not the raw `vector_stores.search()` endpoint** — that was the original
design and it 404'd against this project's store. That endpoint sends an
`OpenAI-Beta: assistants=v2` header (the older Assistants-beta surface);
Foundry's Knowledge item here is typed `ManagedAzureSearch` (visible in the
portal under Build → Agents → Knowledge, not a standalone searchable
resource), and the classic Assistants-beta search route apparently isn't
wired up for that backend. The newer Responses API's tool-based
`file_search` worked instead. If this breaks again on a future SDK/platform
change, re-check that assumption before assuming file_search itself is
unreachable.

**Cite via filename, not a lookup** — every indexed file is named
`<lp_document_id>.txt` (`index_corpus.py`'s materialize step), so a
`file_citation` annotation's `filename` field *is* the citation — no
separate ID resolution needed, and it's traceable to `lp_document_manifest`
for Stage E's citation-accuracy scoring. The system prompt requires
answering only from file_search results and saying so plainly if they don't
actually answer the question, rather than padding with generic commentary.

## How `fusion_agent.py` works

The router (DD-13). Classifies each question, then invokes the already-
independent legs as whole units — deliberately *not* one LLM with tool
access to both legs, which DD-13 explicitly considered and rejected (opaque
routing, and Stage E needs per-leg groundedness/citation-accuracy scores,
not a blended one).

1. **Classify** — a single forced tool call (`classify_question`) with an
   `enum`-constrained `route: "structured" | "document" | "hybrid"`, same
   pattern as `structured_agent.py`'s `sector_group` enum: the output is
   always exactly one of the three, never free text to parse or a guessed
   label.
2. **Dispatch** — `structured`/`document` call that one leg directly;
   `hybrid` calls both.
3. **Synthesise (hybrid only)** — one more LLM call composes the two leg
   outputs into a single coherent answer, instructed to preserve every
   caveat and citation from both and flag it explicitly if they conflict,
   rather than silently picking one.
4. **Partial-failure handling** — in a hybrid run, if one leg raises, the
   other leg's answer is still returned with an explicit note about which
   leg failed, rather than the whole question failing or the gap being
   silently dropped (DD-13: report failure modes honestly).

## How `evaluate_agents.py` works

The evaluation harness (DD-13: groundedness + citation-accuracy, scored
**per leg**, never blended into one number). **Oracle-based, not
LLM-judged** — every LP document is templated from known canonical facts
(`lp_documents.py`: "no LLM calls, no fabricated numeric precision"), and
every DAX measure is independently re-derivable by just running the query.
So instead of asking an LLM to judge whether an answer "seems grounded"
(another non-deterministic layer on top of the thing being evaluated), this
checks agent answers against values already known to be correct — same
philosophy as WS2's reconciliation being scored against `expected_conflicts`
(see `CLAUDE.md`).

- **Structured leg**: 6 fixed (question, oracle DAX) cases spanning
  different measures/filters. The oracle query runs independently of the
  agent — bypassing its own tool-calling and narration — then the agent's
  narrated text is checked for that value via numeric extraction with a
  relative tolerance, trying several scales (raw, ×100 for fraction→percentage,
  ÷1e3/1e6/1e9 for dollar figures abbreviated in prose like "$610.7 million").
  Tests faithfulness: did the agent state what was actually computed, not a
  hallucinated or garbled number.
- **Document leg**: samples 2 real documents per `document_type` from the
  landed corpus and parses their `body_text` against the exact templates in
  `lp_documents.py` (same source of truth, not a separate guess) to get
  known facts and the expected `lp_document_id`. Scores groundedness
  (does the answer contain the actual fact) and citation-accuracy
  (did it cite the right document) **separately** from citation-annotation
  coverage, since `file_citation` annotations are known to not always attach
  even when the answer is genuinely grounded (see `document_agent.py`) —
  conflating "no annotation" with "wrong/no grounding" would be inaccurate.

**Finding (2026-07-20), reproduced across two live runs**: structured leg
6/6 grounded. Document leg 5/6 grounded, 5/6 citation-accuracy, 6/6
annotation coverage — the one consistent failure is disambiguating two
near-duplicate `quarterly_letter` documents from the *same investor* across
different quarters. Across both runs, `file_search` cited a *different*
wrong document each time (`LPD-000058`, then `LPD-000434`) and stated a
different wrong company count each time (8, then 5) — not a fluke or one
confusable pair, a genuine retrieval-ranking weakness specific to this
document type's generic, repetitive phrasing ("The fund's portfolio spans N
companies..."). `capital_call_notice`/`memo` documents, which contain
distinctive dollar amounts and company names, cited correctly 4/4 times.
Recorded honestly rather than tuned away — an eval that always passes isn't
telling you anything.

## Why a separate folder from `data-generator/`

`data-generator/` produces synthetic data with no external dependencies (pure Python,
deterministic, `seed=42`). This folder calls out to a real Azure AI Foundry project —
different dependency profile, different secrets-handling needs, and arguably a
different audience (whoever's driving the AI integration, not necessarily whoever's
tuning conflict rates). Kept separate rather than folded into `data-generator/`.
