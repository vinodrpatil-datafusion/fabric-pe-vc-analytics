"""One-off verification: query the Foundry vector store directly via the API
(bypassing the portal UI, which showed a "Failed files" count that didn't
match index_corpus.py's own success/failure bookkeeping) and report the true
per-file status breakdown, cross-checked against the actual lp_documents
corpus.

Usage:
    python verify_corpus.py
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pandas as pd
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
LANDING_INTERNAL = REPO_ROOT / "sample-data" / "landing" / "internal"


def main() -> int:
    load_dotenv(REPO_ROOT / "ai-integration" / ".env")
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    store_name = os.environ.get("LP_VECTOR_STORE_NAME", "pevc-lp-documents")
    if not endpoint:
        print("AZURE_AI_PROJECT_ENDPOINT not set.")
        return 1

    from azure.ai.projects import AIProjectClient

    docs_path = LANDING_INTERNAL / "lp_documents.parquet"
    corpus_ids = set(pd.read_parquet(docs_path)["lp_document_id"])
    print(f"Corpus: {len(corpus_ids)} lp_document_ids expected.")

    project_client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    client = project_client.get_openai_client()

    vector_store = None
    for vs in client.vector_stores.list():
        if vs.name == store_name:
            vector_store = vs
            break
    if vector_store is None:
        print(f"No vector store named '{store_name}' found.")
        return 1

    print(f"Vector store '{store_name}' (id={vector_store.id}) reports file_counts={vector_store.file_counts}\n")

    # Walk every attached file, keyed by live status -- this hits the API
    # directly rather than trusting the portal's summary card.
    status_counts: Counter[str] = Counter()
    ids_by_status: dict[str, list[str]] = {}
    after = None
    while True:
        page = client.vector_stores.files.list(vector_store_id=vector_store.id, limit=100, after=after)
        if not page.data:
            break
        for vsf in page.data:
            file_obj = client.files.retrieve(vsf.id)
            doc_id = Path(file_obj.filename).stem
            status_counts[vsf.status] += 1
            ids_by_status.setdefault(vsf.status, []).append(doc_id)
        after = page.data[-1].id
        if not getattr(page, "has_more", False):
            break

    print("Live per-file status counts (queried just now, not the cached portal card):")
    for status, count in status_counts.items():
        print(f"  {status}: {count}")

    total_attached = sum(status_counts.values())
    print(f"\nTotal files attached to vector store: {total_attached} (corpus size: {len(corpus_ids)})")

    attached_ids = {doc_id for ids in ids_by_status.values() for doc_id in ids}
    missing = corpus_ids - attached_ids
    extra = attached_ids - corpus_ids
    if missing:
        print(f"\n{len(missing)} corpus document(s) NOT found in the vector store at all: {sorted(missing)}")
    if extra:
        print(f"\n{len(extra)} file(s) in the vector store NOT in the corpus (stale/duplicate?): {sorted(extra)}")

    if "failed" in ids_by_status:
        print(f"\nCurrently failed ({len(ids_by_status['failed'])}): {sorted(ids_by_status['failed'])}")
    if "in_progress" in ids_by_status:
        print(f"\nStill in_progress ({len(ids_by_status['in_progress'])}): {sorted(ids_by_status['in_progress'])}")

    if not missing and not extra and status_counts.get("completed", 0) == len(corpus_ids):
        print("\nFully verified: every corpus document is attached and completed. The portal's "
              "'Failed files' counter appears to be stale/historical, not a live status.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
