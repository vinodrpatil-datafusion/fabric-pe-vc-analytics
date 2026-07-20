"""WS5 Stage C -- custom function-calling agent over the Gold semantic model
(DD-13's structured leg, re-platformed off the native Fabric Data Agent per
the 2026-07-15 revision -- see docs/design_decisions.md).

Answers NL2metric-shaped questions (MOIC, IRR proxy, NAV proxy, sector
concentration, vintage performance) by having an LLM pick one of a small,
fixed set of tool functions -- one per docs/measures.md entry -- each backed
by a parameterized DAX query against `pevc-semantic-model`, run via the Power
BI REST API's executeQueries. The LLM never writes DAX itself: it only
selects a function and fills `vintage_year`/`sector_group`/`as_of_date`
arguments, keeping the actual query surface deterministic and traceable to
the same measure definitions the Power BI report uses (docs/measures.md is
the contract; this script must never re-derive a measure's logic independently).

**One identity, two resource scopes.** This script calls both Azure AI
Foundry (the LLM call) and Fabric/Power BI (the DAX query). Those started out
requiring two different accounts -- confirmed by hitting a real 403 testing
cross-identity access, since neither account initially had access to both
resources. Once one account is granted access to *both* (Fabric portal ->
your workspace -> Manage access -> add the Foundry account; or the Foundry
resource's IAM -> add the Fabric account the "Cognitive Services OpenAI
User" role), a single credential can request tokens for both scopes -- Azure
AD doesn't care that they're different resource audiences, only that the
signed-in principal has each resource's RBAC. Set `STRUCTURED_AGENT_LOGIN_HINT`
in `.env` (git-ignored -- never hardcode an account name here) to that
account so the browser prompt pre-fills it.

Auth uses a single `InteractiveBrowserCredential` with persistent (macOS
Keychain-backed) token caching, so the browser sign-in prompt only appears
once -- the first run, or whenever the cached token needs renewal -- not on
every invocation.

Usage:
    python structured_agent.py "What's the MOIC for the 2022 vintage?"
    python structured_agent.py   # runs a default demo question
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
TOKEN_CACHE_NAME = "fabric-pe-vc-analytics-structured-agent"
EXECUTE_QUERIES_URL_TEMPLATE = (
    "https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
)

DEFAULT_QUESTION = "What's the portfolio's MOIC and IRR (proxy) for the 2022 vintage?"
MAX_TOOL_ROUNDS = 6


def log(msg: str) -> None:
    print(f"[structured_agent] {msg}")


# --- DAX query construction -------------------------------------------------
# Every measure here is quoted verbatim from the TMDL
# (fabric/pevc-dev/pevc-semantic-model.SemanticModel/definition/tables/gold_fact_investment.tmdl)
# -- this script does not redefine measure logic, only slices it.

def _filters(vintage_year: int | None, sector_group: str | None) -> list[str]:
    filters = []
    if vintage_year is not None:
        filters.append(f"gold_dim_investor[vintage_year] = {int(vintage_year)}")
    if sector_group is not None:
        escaped = sector_group.replace('"', '""')
        filters.append(f'gold_dim_company[sector_group] = "{escaped}"')
    return filters


def _row_query(measure_pairs: str, filters: list[str]) -> str:
    if filters:
        filter_clause = ",\n    ".join(filters)
        return f"EVALUATE\nCALCULATETABLE(\n    ROW({measure_pairs}),\n    {filter_clause}\n)"
    return f"EVALUATE\nROW({measure_pairs})"


def dax_total_invested(vintage_year: int | None = None, sector_group: str | None = None) -> str:
    return _row_query('"Total Invested", [Total Invested]', _filters(vintage_year, sector_group))


def dax_nav_proxy(vintage_year: int | None = None, sector_group: str | None = None) -> str:
    return _row_query('"NAV (proxy)", [NAV (proxy)]', _filters(vintage_year, sector_group))


def dax_moic(vintage_year: int | None = None, sector_group: str | None = None) -> str:
    return _row_query('"MOIC", [MOIC]', _filters(vintage_year, sector_group))


def dax_irr_proxy(vintage_year: int | None = None, sector_group: str | None = None) -> str:
    return _row_query('"IRR (proxy)", [IRR (proxy)]', _filters(vintage_year, sector_group))


def dax_cost_weighted_avg_years_held(vintage_year: int | None = None, sector_group: str | None = None) -> str:
    return _row_query(
        '"Cost-Weighted Avg Years Held", [Cost-Weighted Avg Years Held]',
        _filters(vintage_year, sector_group),
    )


def dax_sector_concentration(vintage_year: int | None = None) -> str:
    filters = _filters(vintage_year, None)
    table_expr = (
        "SUMMARIZECOLUMNS(\n"
        '    gold_dim_company[sector_group],\n'
        '    "Sector Concentration %", [Sector Concentration %],\n'
        '    "Total Invested", [Total Invested]\n'
        ")"
    )
    if filters:
        filter_clause = ",\n    ".join(filters)
        return f"EVALUATE\nCALCULATETABLE(\n{table_expr},\n    {filter_clause}\n)"
    return f"EVALUATE\n{table_expr}"


def dax_list_sector_groups() -> str:
    return "EVALUATE\nVALUES(gold_dim_company[sector_group])"


def dax_cumulative_nav_proxy(as_of_date: str | None = None) -> str:
    date_expr = f'DATE({as_of_date.replace("-", ",")})' if as_of_date else "TODAY()"
    return (
        "EVALUATE\n"
        "CALCULATETABLE(\n"
        '    ROW("Cumulative NAV (proxy)", [Cumulative NAV (proxy)]),\n'
        f"    gold_dim_date[date] = {date_expr}\n"
        ")"
    )


# --- Power BI executeQueries call -------------------------------------------

def run_dax_query(fabric_token: str, workspace_id: str, dataset_id: str, dax: str) -> list[dict[str, Any]]:
    url = EXECUTE_QUERIES_URL_TEMPLATE.format(workspace_id=workspace_id, dataset_id=dataset_id)
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {fabric_token}", "Content-Type": "application/json"},
        json={"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["results"][0]["tables"][0]["rows"]


def fetch_sector_groups(fabric_token: str, workspace_id: str, dataset_id: str) -> list[str]:
    """Live distinct sector_group values -- fetched once at startup and used to
    constrain the LLM's tool-call arguments (see build_tools). Not hardcoded:
    the generator's full taxonomy (data-generator/pevc_generator/reference.py)
    has 8 groups, but which ones actually have companies in a given dataset
    scale/seed can vary -- seen in practice: 'Climate' didn't appear at all in
    a live query. A guessed static list would drift from real data."""
    rows = run_dax_query(fabric_token, workspace_id, dataset_id, dax_list_sector_groups())
    values = {next(iter(row.values())) for row in rows if row}
    return sorted(v for v in values if v is not None)


# --- Tool definitions (OpenAI function-calling schema) ----------------------

def _vintage_year_param() -> dict[str, Any]:
    return {"type": "integer", "description": "Optional: filter to a single fund vintage year."}


def _sector_group_param(sector_groups: list[str], extra: str = "") -> dict[str, Any]:
    return {
        "type": "string",
        "enum": sector_groups,
        "description": f"Optional: filter to a single sector_group. Must be one of the listed values -- "
                        f"there is no free-text sector name in this model.{(' ' + extra) if extra else ''}",
    }


def build_tools(sector_groups: list[str]) -> list[dict[str, Any]]:
    """Tool schema is built at runtime, not module load, because sector_group
    is constrained to a JSON Schema `enum` of live values (see
    fetch_sector_groups) -- this makes it structurally impossible for the LLM
    to guess a plausible-sounding but wrong sector name (e.g. 'Tech',
    'FinTech' -- a sub-tag, not a sector_group) that would silently return an
    empty result indistinguishable from a genuinely blank measure."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_total_invested",
                "description": "Capital actually deployed into portfolio companies (cost basis, not committed capital). "
                                "docs/measures.md: 'Total Invested'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vintage_year": _vintage_year_param(),
                        "sector_group": _sector_group_param(sector_groups),
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_nav_proxy",
                "description": "Estimated current worth of the portfolio -- realised proceeds for exited positions plus "
                                "unrealised positions held at cost (1.0x). NOT an audited/GP-marked NAV -- see "
                                "docs/measures.md caveat before presenting as fact.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vintage_year": _vintage_year_param(),
                        "sector_group": _sector_group_param(sector_groups),
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_moic",
                "description": "Multiple on Invested Capital (pooled, not simple-averaged) -- realised + unrealised value "
                                "over deployed capital. Non-additive across slices; ignores holding period (pair with "
                                "IRR proxy). docs/measures.md: 'MOIC'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vintage_year": _vintage_year_param(),
                        "sector_group": _sector_group_param(sector_groups),
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_irr_proxy",
                "description": "Time-adjusted annualised return, single lump-sum-flow assumption -- directionally correct "
                                "for ranking vintages/sectors/funds, NOT an audited money-weighted IRR. "
                                "docs/measures.md: 'IRR (proxy)'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vintage_year": _vintage_year_param(),
                        "sector_group": _sector_group_param(sector_groups),
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_sector_concentration",
                "description": "Share of deployed capital by sector_group -- always returns the full sector breakdown "
                                "table (percentages sum to 100% within any outer filter). Use this first if you need "
                                "to know which sector had the best/worst MOIC or IRR -- it returns every sector's "
                                "Total Invested in one call, then follow up get_moic/get_irr_proxy per sector_group "
                                "of interest rather than guessing which sectors exist. "
                                "docs/measures.md: 'Sector Concentration %'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vintage_year": {"type": "integer", "description": "Optional: restrict the breakdown to a single fund vintage year."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_cost_weighted_avg_years_held",
                "description": "Holding-period input to IRR (proxy), weighted by participation_amount. Drifts daily for "
                                "unrealised (open) positions since it uses TODAY(). Supporting measure, docs/measures.md.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vintage_year": _vintage_year_param(),
                        "sector_group": _sector_group_param(sector_groups),
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_cumulative_nav_proxy",
                "description": "Running NAV-proxy total as of a given date (defaults to today if not given) -- for trend "
                                "questions, not a portfolio snapshot. Supporting measure, docs/measures.md.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "as_of_date": {"type": "string", "description": "Optional ISO date (YYYY-MM-DD). Defaults to today."},
                    },
                },
            },
        },
    ]


def dispatch_tool_call(name: str, args: dict[str, Any], fabric_token: str, workspace_id: str, dataset_id: str) -> Any:
    dax_builders = {
        "get_total_invested": dax_total_invested,
        "get_nav_proxy": dax_nav_proxy,
        "get_moic": dax_moic,
        "get_irr_proxy": dax_irr_proxy,
        "get_sector_concentration": dax_sector_concentration,
        "get_cost_weighted_avg_years_held": dax_cost_weighted_avg_years_held,
        "get_cumulative_nav_proxy": dax_cumulative_nav_proxy,
    }
    builder = dax_builders.get(name)
    if builder is None:
        return {"error": f"Unknown tool '{name}'"}

    dax = builder(**args)
    log(f"Running DAX for {name}({args}):\n{dax}")
    try:
        rows = run_dax_query(fabric_token, workspace_id, dataset_id, dax)
    except requests.HTTPError as e:
        return {"error": f"executeQueries failed: {e.response.status_code} {e.response.text[:500]}"}
    if not rows:
        # Distinguishes "this filter combination matched zero rows" from a
        # measure that's genuinely blank -- an LLM given just `[]` can't tell
        # those apart and, in practice, narrated it as "no data available"
        # (reading as a data gap) when the real cause was an invalid filter.
        return {"error": f"No rows matched this filter combination ({args}). "
                          f"If sector_group was set, confirm it's one of the enum values -- "
                          f"do not retry with a guessed variant."}
    return rows


SYSTEM_PROMPT = (
    "You are the structured-retrieval leg of a PE/VC portfolio analytics fusion agent, answering "
    "questions from an LP's vantage point over a consolidated fund-of-funds portfolio (no per-LP "
    "position data exists -- see docs/measures.md). Always use the provided tools to get real numbers; "
    "never estimate or recall a figure from your own knowledge. When a tool result includes a caveat "
    "(e.g. NAV proxy uses cost-basis for unrealised positions, IRR proxy assumes a single lump-sum flow), "
    "state it briefly rather than presenting the number as an audited fact. Cite the measure name(s) you used."
)


def main() -> int:
    load_dotenv(REPO_ROOT / "ai-integration" / ".env")
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT")
    workspace_id = os.environ.get("POWERBI_WORKSPACE_ID")
    dataset_id = os.environ.get("POWERBI_DATASET_ID")
    missing = [
        name for name, val in [
            ("AZURE_AI_PROJECT_ENDPOINT", endpoint),
            ("AZURE_AI_MODEL_DEPLOYMENT", deployment),
            ("POWERBI_WORKSPACE_ID", workspace_id),
            ("POWERBI_DATASET_ID", dataset_id),
        ] if not val
    ]
    if missing:
        log(f"Missing required .env values: {', '.join(missing)}")
        return 1

    from azure.ai.projects import AIProjectClient

    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    log(f"Question: {question}")

    # Single credential, persistently cached (macOS Keychain) -- requires the
    # signed-in account to have RBAC on *both* resources (see module
    # docstring). One browser prompt on first run, silent reuse after that.
    login_hint = os.environ.get("STRUCTURED_AGENT_LOGIN_HINT")
    log("Authenticating (cached after first run -- see STRUCTURED_AGENT_LOGIN_HINT in .env for which account)...")
    credential = InteractiveBrowserCredential(
        login_hint=login_hint,
        cache_persistence_options=TokenCachePersistenceOptions(name=TOKEN_CACHE_NAME),
    )
    credential.get_token(FOUNDRY_SCOPE)
    project_client = AIProjectClient(endpoint=endpoint, credential=credential)
    openai_client = project_client.get_openai_client()

    fabric_token = credential.get_token(POWERBI_SCOPE).token

    sector_groups = fetch_sector_groups(fabric_token, workspace_id, dataset_id)
    log(f"Live sector_group values: {sector_groups}")
    tools = build_tools(sector_groups)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    # Loop, not a single round-trip: a question like "which sector performed
    # best" needs get_sector_concentration (to learn which sectors exist)
    # *then* get_moic per sector -- multiple sequential tool calls before any
    # final text answer. A fixed one-shot follow-up printed "None" whenever
    # the second response was itself another tool call rather than text.
    for _ in range(MAX_TOOL_ROUNDS):
        response = openai_client.chat.completions.create(model=deployment, messages=messages, tools=tools)
        choice = response.choices[0]

        if not choice.message.tool_calls:
            if not choice.message.content:
                log("Model returned an empty final response (no tool_calls, no content) -- rerun the question.")
                return 1
            print(f"\n{choice.message.content}")
            return 0

        messages.append(choice.message)
        for tool_call in choice.message.tool_calls:
            args = json.loads(tool_call.function.arguments or "{}")
            result = dispatch_tool_call(tool_call.function.name, args, fabric_token, workspace_id, dataset_id)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })

    log(f"Gave up after {MAX_TOOL_ROUNDS} tool-call rounds without a final answer.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
