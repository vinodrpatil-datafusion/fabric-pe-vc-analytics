"""WS5 Stage B — index the LP document corpus in Azure AI Foundry (DD-13, DD-17).

Materializes each `lp_documents` row (data_model.md §1.9) as one small text file
and uploads the set into a Foundry vector store, so the document-retrieval leg
of the fusion agent can search over them (file_search). Each file is named by
`lp_document_id` and carries that ID inside its own text, so a retrieved chunk
is traceable back to `lp_document_manifest` (§1.10) for citation-accuracy
scoring later (Stage E).

**SDK surface (confirmed against azure-ai-projects==2.3.0 / openai==2.45.0):**
`AIProjectClient` no longer exposes `.agents.vector_stores`/`.agents.files` --
`AgentsOperations` in this version is a different (session/version-based)
resource model. Vector-store and file-search operations instead live on the
OpenAI-compatible client returned by `AIProjectClient.get_openai_client()`,
following the standard `openai` SDK's Assistants-style surface:
`openai_client.vector_stores` and `openai_client.vector_stores.files`. If a
future SDK bump breaks this again, `pip show azure-ai-projects` and re-check
`dir(AIProjectClient)` / `dir(openai_client.vector_stores)` before assuming
the approach itself is wrong.

Idempotency: coarse, not per-file. If a vector store named
LP_VECTOR_STORE_NAME already exists and already has >= len(corpus)
*completed* files attached, the script reports status and exits without
re-uploading. To force a clean rebuild, delete the vector store in the
Foundry portal first. (Checks `file_counts.completed`, not `.total` --
`total` also counts failed files, which would otherwise let a partially-
failed run masquerade as fully indexed on the next run.)

Per-file upload failures (seen in practice: a couple of files failing
transiently early in a ~1,568-file run, unrelated to content) are retried a
few times before being given up on; any files still failed at the end are
listed by lp_document_id so they can be investigated or the run repeated.

Per-file polling is capped at POLL_TIMEOUT_SECONDS -- the SDK's own
upload_and_poll has no timeout and will wait indefinitely if a file's
server-side processing stalls (seen in practice: one file left a run hung
for over an hour with 0% CPU, one idle connection open). A file still
"in_progress" past the cap is treated as a failed attempt and retried.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # fill in your project endpoint
    python index_corpus.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
LANDING_INTERNAL = REPO_ROOT / "sample-data" / "landing" / "internal"
MAX_UPLOAD_ATTEMPTS = 3
POLL_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_corpus() -> pd.DataFrame:
    docs_path = LANDING_INTERNAL / "lp_documents.parquet"
    if not docs_path.exists():
        docs_path = docs_path.with_suffix(".csv")
    reader = pd.read_parquet if docs_path.suffix == ".parquet" else pd.read_csv
    df = reader(docs_path)
    log(f"Loaded {len(df)} lp_documents from {docs_path.relative_to(REPO_ROOT)}")
    return df


def materialize_documents(corpus: pd.DataFrame, out_dir: Path) -> list[Path]:
    """One small .txt per document, named by lp_document_id, ID stated inside
    the text too -- so a retrieved chunk is traceable even without the manifest."""
    paths = []
    for row in corpus.itertuples():
        text = (
            f"Document ID: {row.lp_document_id}\n"
            f"Type: {row.document_type}\n"
            f"Fund (investor_id): {row.investor_id}\n"
            f"Effective date: {row.effective_date}\n\n"
            f"{row.body_text}\n"
        )
        p = out_dir / f"{row.lp_document_id}.txt"
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    return paths


def get_or_create_vector_store(openai_client, name: str, expected_count: int):
    """Reuse an existing vector store by name if it already has the expected
    file count; otherwise create a new one. Coarse idempotency -- see module
    docstring."""
    existing = None
    for vs in openai_client.vector_stores.list():
        if vs.name == name:
            existing = vs
            break

    if existing is not None:
        completed_count = getattr(existing.file_counts, "completed", None)
        log(f"Found existing vector store '{name}' (id={existing.id}), file_counts={existing.file_counts}")
        if completed_count is not None and completed_count >= expected_count:
            log("Already fully indexed -- skipping upload. Delete the vector store in the "
                "Foundry portal first if you want a clean rebuild.")
            return existing, True
        return existing, False

    log(f"No existing vector store named '{name}' -- creating a new one.")
    vs = openai_client.vector_stores.create(name=name)
    return vs, False


def upload_and_poll_with_timeout(openai_client, vector_store_id: str, path: Path):
    """Upload+attach one file, then poll for a terminal status ourselves
    (instead of the SDK's upload_and_poll, which has no timeout and will wait
    forever if a file's processing stalls server-side -- seen in practice: a
    single file left an entire ~1,568-file run hung for over an hour). Returns
    the last-seen VectorStoreFile; status is left as "in_progress" if
    POLL_TIMEOUT_SECONDS is exceeded, which the caller treats as a failure."""
    with open(path, "rb") as f:
        result = openai_client.vector_stores.files.upload(vector_store_id=vector_store_id, file=f)

    start = time.monotonic()
    while result.status == "in_progress" and time.monotonic() - start < POLL_TIMEOUT_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
        result = openai_client.vector_stores.files.retrieve(result.id, vector_store_id=vector_store_id)
    return result


def discard_attempt(openai_client, vector_store_id: str, result) -> None:
    """Remove a non-completed attachment (and its underlying file) before
    retrying, so a failed/stuck attempt doesn't linger as an orphaned
    duplicate once a later attempt succeeds -- seen in practice: 3 files that
    failed once then succeeded on retry left 3 orphaned "failed" attachments
    behind, inflating the vector store's total file count past the corpus
    size. Best-effort: cleanup failures here shouldn't abort the run."""
    try:
        openai_client.vector_stores.files.delete(result.id, vector_store_id=vector_store_id)
    except Exception as e:
        log(f"    (cleanup) could not detach {result.id}: {e}")
    try:
        openai_client.files.delete(result.id)
    except Exception as e:
        log(f"    (cleanup) could not delete underlying file {result.id}: {e}")


def upload_one(openai_client, vector_store_id: str, path: Path):
    """Upload+attach a single file, retrying a few times on transient failure
    or a stalled-processing timeout. Returns the final VectorStoreFile
    (status may still be "failed"/"in_progress" if every attempt failed)."""
    result = None
    for attempt in range(1, MAX_UPLOAD_ATTEMPTS + 1):
        result = upload_and_poll_with_timeout(openai_client, vector_store_id, path)
        if result.status == "completed":
            return result

        reason = result.last_error or (
            f"timed out after {POLL_TIMEOUT_SECONDS}s still in_progress" if result.status == "in_progress"
            else result.status
        )
        verb = "retrying" if attempt < MAX_UPLOAD_ATTEMPTS else "giving up"
        log(f"  {path.stem}: attempt {attempt} status={result.status} ({reason}) -- {verb}")
        discard_attempt(openai_client, vector_store_id, result)
    return result


def upload_and_attach(openai_client, vector_store, paths: list[Path]) -> list[str]:
    """Returns the lp_document_ids (from filename stem) that never reached
    "completed" status after retries."""
    log(f"Uploading {len(paths)} files to vector store '{vector_store.name}'...")
    start = time.monotonic()
    failed_ids = []
    for i, p in enumerate(paths, start=1):
        result = upload_one(openai_client, vector_store.id, p)
        if result.status != "completed":
            failed_ids.append(p.stem)
        if i % 100 == 0 or i == len(paths):
            elapsed = time.monotonic() - start
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (len(paths) - i) / rate if rate > 0 else 0
            log(f"  {i}/{len(paths)} processed -- elapsed {elapsed / 60:.1f}m, "
                f"~{remaining / 60:.1f}m remaining at current rate")
    return failed_ids


def main() -> int:
    load_dotenv(REPO_ROOT / "ai-integration" / ".env")
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    store_name = os.environ.get("LP_VECTOR_STORE_NAME", "pevc-lp-documents")
    if not endpoint:
        log("AZURE_AI_PROJECT_ENDPOINT not set -- copy .env.example to .env and fill it in.")
        return 1

    from azure.ai.projects import AIProjectClient  # deferred: only needed once endpoint is confirmed set

    corpus = load_corpus()

    with tempfile.TemporaryDirectory(prefix="lp_corpus_") as tmp:
        paths = materialize_documents(corpus, Path(tmp))
        log(f"Materialized {len(paths)} document files in a temp directory.")

        project_client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
        openai_client = project_client.get_openai_client()
        vector_store, already_done = get_or_create_vector_store(openai_client, store_name, len(paths))
        failed_ids: list[str] = []
        if not already_done:
            failed_ids = upload_and_attach(openai_client, vector_store, paths)

    if failed_ids:
        log(f"{len(failed_ids)} file(s) still failed after {MAX_UPLOAD_ATTEMPTS} attempts each: "
            f"{', '.join(failed_ids)}")
        log("Re-running the script will retry (idempotency check is against completed-file count, "
            "which these are excluded from).")
        return 1

    log(f"Done. Vector store: name={store_name} id={vector_store.id}")
    log("Next: Stage C (structured-retrieval agent), then Stage D wires this vector store "
        "into a file_search-enabled agent for the document-retrieval leg.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
