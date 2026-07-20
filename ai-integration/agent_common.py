"""Shared auth/env plumbing for WS5's fusion agent (DD-13) and its two legs.

Extracted out of structured_agent.py once a second leg (document_agent.py)
and a router (fusion_agent.py) needed the same setup -- authenticating
separately per leg would mean multiple browser prompts (and multiple
Foundry/Fabric client instances) for what should be one signed-in session
covering a single run. `build_context()` authenticates once and returns
everything every leg needs; legs stay independently runnable (each still has
its own `main()`) because DD-13 requires them independently evaluable, not
because they don't share plumbing.

See structured_agent.py's original docstring (still accurate) for why this
needs one identity with RBAC on two separate resources, and why the
InteractiveBrowserCredential is configured the way it is.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

import openai
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
TOKEN_CACHE_NAME = "fabric-pe-vc-analytics-structured-agent"
MAX_LLM_CALL_ATTEMPTS = 3
LLM_CALL_RETRY_DELAY_SECONDS = 3

T = TypeVar("T")


def log(prefix: str, msg: str) -> None:
    print(f"[{prefix}] {msg}")


def call_with_retry(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Retries a transient-looking API failure -- seen in practice: a
    `401 PermissionDenied` from a fully-permissioned account that resolved
    itself on a bare retry seconds later (fusion_agent.py's classify_question
    call), same class of flakiness as index_corpus.py's upload retries.
    Catches openai.APIStatusError (covers 401/429/5xx alike -- deliberately
    broad, since a *permanent* permission gap will just keep failing after
    MAX_LLM_CALL_ATTEMPTS and still surface, same as before this existed) and
    openai.APIConnectionError. Intended for openai_client.chat.completions.create
    / .responses.create calls specifically, not arbitrary callables."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_LLM_CALL_ATTEMPTS + 1):
        try:
            return fn(*args, **kwargs)
        except (openai.APIStatusError, openai.APIConnectionError) as e:
            last_error = e
            if attempt < MAX_LLM_CALL_ATTEMPTS:
                log("agent_common", f"LLM call attempt {attempt} failed ({e}) -- "
                                     f"retrying in {LLM_CALL_RETRY_DELAY_SECONDS}s")
                time.sleep(LLM_CALL_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


@dataclass
class AgentContext:
    openai_client: Any
    fabric_token: str
    workspace_id: str
    dataset_id: str
    deployment: str
    vector_store_name: str


def build_context() -> AgentContext:
    """Loads .env, authenticates once (single browser prompt, persistently
    cached), and returns a ready-to-use context. Raises RuntimeError if
    required .env values are missing -- callers should catch that and exit
    non-zero rather than let a bare traceback surface."""
    load_dotenv(REPO_ROOT / "ai-integration" / ".env")
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT")
    workspace_id = os.environ.get("POWERBI_WORKSPACE_ID")
    dataset_id = os.environ.get("POWERBI_DATASET_ID")
    vector_store_name = os.environ.get("LP_VECTOR_STORE_NAME", "pevc-lp-documents")
    missing = [
        name for name, val in [
            ("AZURE_AI_PROJECT_ENDPOINT", endpoint),
            ("AZURE_AI_MODEL_DEPLOYMENT", deployment),
            ("POWERBI_WORKSPACE_ID", workspace_id),
            ("POWERBI_DATASET_ID", dataset_id),
        ] if not val
    ]
    if missing:
        raise RuntimeError(f"Missing required .env values: {', '.join(missing)}")

    from azure.ai.projects import AIProjectClient

    login_hint = os.environ.get("AGENT_LOGIN_HINT")
    log("agent_common", "Authenticating (cached after first run -- see AGENT_LOGIN_HINT in .env for which account)...")
    credential = InteractiveBrowserCredential(
        login_hint=login_hint,
        cache_persistence_options=TokenCachePersistenceOptions(name=TOKEN_CACHE_NAME),
    )
    credential.get_token(FOUNDRY_SCOPE)
    project_client = AIProjectClient(endpoint=endpoint, credential=credential)
    openai_client = project_client.get_openai_client()

    fabric_token = credential.get_token(POWERBI_SCOPE).token

    return AgentContext(
        openai_client=openai_client,
        fabric_token=fabric_token,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        deployment=deployment,
        vector_store_name=vector_store_name,
    )
