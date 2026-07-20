"""WS5 Stage D leg -- document-retrieval agent over the LP document corpus
(DD-13's unstructured leg: Foundry IQ / vector-store search over the Stage B
corpus indexed by index_corpus.py, sourced from DD-17's synthetic documents).

Uses the OpenAI Responses API's built-in `file_search` tool -- retrieval and
narration happen in one call, with citations coming back as `file_citation`
annotations on the output text. This replaced an earlier design based on the
raw `vector_stores.search()` convenience endpoint, which 404'd against this
project's vector store: that endpoint sends an `OpenAI-Beta: assistants=v2`
header, and Foundry's Knowledge item here is typed `ManagedAzureSearch`
(visible in the portal under Build -> Agents -> Knowledge, not a standalone
searchable resource) -- the classic Assistants-beta search route apparently
isn't wired up for that backend, while the newer Responses API's tool-based
file_search is. If this breaks again on a future SDK/platform change, that's
the first thing to re-check, not a sign file_search itself is unreachable.

Since index_corpus.py names every uploaded file `<lp_document_id>.txt`, a
citation's `filename` field is the lp_document_id directly -- no separate ID
lookup needed, and every cited chunk is traceable back to
`lp_document_manifest` for Stage E's citation-accuracy scoring.

Usage:
    python document_agent.py "What have LP quarterly letters said about portfolio risk?"
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from agent_common import build_context, call_with_retry, log as _common_log

DEFAULT_QUESTION = "What have LP quarterly letters said about portfolio risk?"
MAX_RESULTS = 8


def log(msg: str) -> None:
    _common_log("document_agent", msg)


def find_vector_store_id(openai_client: Any, name: str) -> str:
    for vs in openai_client.vector_stores.list():
        if vs.name == name:
            return vs.id
    raise RuntimeError(f"No vector store named '{name}' found -- has index_corpus.py (Stage B) been run?")


SYSTEM_PROMPT = (
    "You are the document-retrieval leg of a PE/VC portfolio analytics fusion agent. "
    "Answer ONLY using the file_search results -- never invent facts, figures, or quotes "
    "that aren't in them. If the results don't actually answer the question, say so "
    "plainly rather than guessing or padding with generic commentary."
)


def answer_document(openai_client: Any, deployment: str, vector_store_id: str, question: str) -> str:
    """Runs one Responses API call with the built-in file_search tool and
    returns the narrated, citation-grounded answer. Raises RuntimeError if
    the model returns no text."""
    response = call_with_retry(
        openai_client.responses.create,
        model=deployment,
        instructions=SYSTEM_PROMPT,
        input=question,
        tools=[{"type": "file_search", "vector_store_ids": [vector_store_id], "max_num_results": MAX_RESULTS}],
    )

    doc_ids = set()
    for item in response.output:
        if item.type == "message":
            for part in item.content:
                if part.type == "output_text":
                    for ann in part.annotations:
                        if ann.type == "file_citation":
                            doc_ids.add(Path(ann.filename).stem)
    if doc_ids:
        log(f"Cited {len(doc_ids)} document(s): {sorted(doc_ids)}")
    else:
        # Not proof retrieval found nothing -- seen in practice: the model
        # can incorporate file_search content into its answer (real company
        # names, specifics) without attaching inline file_citation markers to
        # those sentences. Absence of annotations means "no formal citation
        # was attached", not "nothing relevant was found".
        log("No file_citation annotations attached -- inconclusive on whether file_search found anything "
            "relevant; check the answer text itself, not just this log line.")

    if not response.output_text:
        raise RuntimeError("Model returned an empty response for the document leg.")
    return response.output_text


def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    log(f"Question: {question}")

    try:
        ctx = build_context()
    except RuntimeError as e:
        log(str(e))
        return 1

    try:
        vector_store_id = find_vector_store_id(ctx.openai_client, ctx.vector_store_name)
        answer = answer_document(ctx.openai_client, ctx.deployment, vector_store_id, question)
    except RuntimeError as e:
        log(str(e))
        return 1

    print(f"\n{answer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
