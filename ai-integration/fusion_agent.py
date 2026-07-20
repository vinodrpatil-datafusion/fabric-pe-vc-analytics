"""WS5 Stage D -- fusion agent (DD-13): routes each question to the structured
leg (structured_agent.py), document leg (document_agent.py), or both, then
composes a hybrid answer.

Per DD-13's own rationale, this deliberately does NOT give one LLM tool
access to both legs at once -- that alternative was explicitly considered and
rejected in the design log: routing logic and failure modes become opaque
inside one prompt, and Stage E's evaluation needs per-leg groundedness /
citation-accuracy scores, not a blended number. Instead: an explicit
classification call decides the route first, then the already-independent
legs are invoked as whole, separately-callable units -- each stays exactly
as evaluable on its own as it was before this file existed.

Classification uses a single forced tool call with an `enum`-constrained
`route` argument (same pattern as structured_agent.py's sector_group enum)
so the output is always exactly one of "structured"/"document"/"hybrid" --
never free text to parse or a guessed label.

Usage:
    python fusion_agent.py "What's the MOIC for the 2022 vintage?"
    python fusion_agent.py "What did the Q3 2025 letters say about risk?"
    python fusion_agent.py "How did FinTech perform, and what did LPs say about it?"
"""

from __future__ import annotations

import json
import sys
from typing import Any

from agent_common import AgentContext, build_context, call_with_retry, log as _common_log
from document_agent import answer_document, find_vector_store_id
from structured_agent import answer_structured

DEFAULT_QUESTION = "What's the portfolio's MOIC for the 2022 vintage?"

ROUTE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "classify_question",
            "description": "Classify which retrieval leg(s) can answer this question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "route": {
                        "type": "string",
                        "enum": ["structured", "document", "hybrid"],
                        "description": (
                            "'structured': needs a computed metric (MOIC, IRR, NAV, sector "
                            "concentration, vintage performance) from the Gold semantic model. "
                            "'document': needs something only stated in an LP document (quarterly "
                            "letter, capital call notice, memo) -- narrative, qualitative, or a "
                            "specific quote/claim. 'hybrid': needs both -- e.g. a metric AND "
                            "commentary/context that only a document would contain."
                        ),
                    },
                },
                "required": ["route"],
            },
        },
    },
]

CLASSIFIER_SYSTEM_PROMPT = (
    "You route questions for a PE/VC portfolio analytics fusion agent to one or both of two "
    "retrieval legs. Call classify_question exactly once with your decision. When genuinely "
    "unsure, prefer 'hybrid' over guessing wrong and missing half the answer."
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You are the fusion layer of a PE/VC portfolio analytics agent, composing one final answer "
    "from two independent leg outputs: a structured-metrics answer and a document-grounded "
    "answer. Combine them into a single coherent answer -- do not just concatenate them. "
    "Preserve every caveat and citation (measure names, lp_document_ids) from both. If the two "
    "legs seem to conflict, say so explicitly rather than picking one silently."
)


def log(msg: str) -> None:
    _common_log("fusion_agent", msg)


def classify_question(openai_client: Any, deployment: str, question: str) -> str:
    messages = [
        {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    response = call_with_retry(
        openai_client.chat.completions.create,
        model=deployment,
        messages=messages,
        tools=ROUTE_TOOL,
        tool_choice={"type": "function", "function": {"name": "classify_question"}},
    )
    tool_call = response.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    return args["route"]


def synthesize(openai_client: Any, deployment: str, question: str, structured_answer: str, document_answer: str) -> str:
    messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Question: {question}\n\n"
            f"Structured leg answer:\n{structured_answer}\n\n"
            f"Document leg answer:\n{document_answer}"
        )},
    ]
    response = call_with_retry(openai_client.chat.completions.create, model=deployment, messages=messages)
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Model returned an empty response synthesising the hybrid answer.")
    return content


def answer_hybrid(ctx: AgentContext, question: str) -> str:
    """Runs both legs independently and synthesises. A single leg failing
    doesn't sink the whole answer -- reports the failure explicitly alongside
    whatever the other leg found, per DD-13's "report failure modes honestly"
    stance, rather than either silently dropping it or aborting entirely."""
    structured_answer = None
    document_answer = None
    errors: list[str] = []

    # Catches Exception broadly, not just RuntimeError -- a leg can fail with
    # an SDK/HTTP error (openai.NotFoundError, requests.HTTPError, etc.) that
    # isn't ours to subclass. The whole point of this function is that one
    # leg's real-world failure degrades gracefully instead of losing the
    # other leg's answer too.
    try:
        structured_answer = answer_structured(ctx.openai_client, ctx.deployment, ctx.fabric_token,
                                               ctx.workspace_id, ctx.dataset_id, question)
    except Exception as e:
        errors.append(f"structured leg failed: {e}")

    try:
        vector_store_id = find_vector_store_id(ctx.openai_client, ctx.vector_store_name)
        document_answer = answer_document(ctx.openai_client, ctx.deployment, vector_store_id, question)
    except Exception as e:
        errors.append(f"document leg failed: {e}")

    if structured_answer is None and document_answer is None:
        raise RuntimeError("; ".join(errors))
    if structured_answer is None:
        return f"{document_answer}\n\n(Note: the structured-metrics leg failed -- {errors[0]})"
    if document_answer is None:
        return f"{structured_answer}\n\n(Note: the document-retrieval leg failed -- {errors[0]})"
    return synthesize(ctx.openai_client, ctx.deployment, question, structured_answer, document_answer)


def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    log(f"Question: {question}")

    try:
        ctx = build_context()
    except RuntimeError as e:
        log(str(e))
        return 1

    route = classify_question(ctx.openai_client, ctx.deployment, question)
    log(f"Route: {route}")

    try:
        if route == "structured":
            answer = answer_structured(ctx.openai_client, ctx.deployment, ctx.fabric_token, ctx.workspace_id,
                                        ctx.dataset_id, question)
        elif route == "document":
            vector_store_id = find_vector_store_id(ctx.openai_client, ctx.vector_store_name)
            answer = answer_document(ctx.openai_client, ctx.deployment, vector_store_id, question)
        else:
            answer = answer_hybrid(ctx, question)
    except Exception as e:
        # Broad on purpose, unlike structured_agent.py/document_agent.py's
        # own main() (RuntimeError only) -- this is the composed entry point
        # a user actually runs, so a clean logged failure beats a raw SDK
        # traceback here. The single-leg scripts stay narrower because a
        # full traceback is more useful while debugging one leg directly
        # (it's exactly how the file_search 404 got diagnosed).
        log(f"{route} route failed: {e}")
        return 1

    print(f"\n{answer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
