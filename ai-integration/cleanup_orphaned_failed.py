"""One-off cleanup: remove orphaned "failed" file attachments left behind by
index_corpus.py's earlier retry logic (fixed now, see discard_attempt() in
index_corpus.py) -- a file that failed once then succeeded on retry left the
failed attempt's attachment behind instead of removing it.

Safety check: only deletes a failed attachment if a *completed* attachment
for the same lp_document_id also exists, so this can't accidentally remove
the only copy of a document that never actually succeeded.

Usage:
    python cleanup_orphaned_failed.py
"""

from __future__ import annotations

import os
from pathlib import Path

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    load_dotenv(REPO_ROOT / "ai-integration" / ".env")
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    store_name = os.environ.get("LP_VECTOR_STORE_NAME", "pevc-lp-documents")
    if not endpoint:
        print("AZURE_AI_PROJECT_ENDPOINT not set.")
        return 1

    from azure.ai.projects import AIProjectClient

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

    print(f"Vector store '{store_name}' (id={vector_store.id}) file_counts={vector_store.file_counts}")

    completed_doc_ids: set[str] = set()
    failed_entries: list[tuple[str, str]] = []  # (vector_store_file_id, doc_id)
    after = None
    while True:
        page = client.vector_stores.files.list(vector_store_id=vector_store.id, limit=100, after=after)
        if not page.data:
            break
        for vsf in page.data:
            file_obj = client.files.retrieve(vsf.id)
            doc_id = Path(file_obj.filename).stem
            if vsf.status == "completed":
                completed_doc_ids.add(doc_id)
            elif vsf.status == "failed":
                failed_entries.append((vsf.id, doc_id))
        after = page.data[-1].id
        if not page.has_more:
            break

    print(f"Found {len(failed_entries)} failed attachment(s).")

    deleted = 0
    for vsf_id, doc_id in failed_entries:
        if doc_id not in completed_doc_ids:
            print(f"  SKIPPING {doc_id} (vsf={vsf_id}) -- no completed copy exists, not safe to delete.")
            continue
        client.vector_stores.files.delete(vsf_id, vector_store_id=vector_store.id)
        client.files.delete(vsf_id)
        print(f"  Deleted orphaned failed attachment for {doc_id} (vsf={vsf_id})")
        deleted += 1

    print(f"\nDeleted {deleted}/{len(failed_entries)} orphaned failed attachment(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
