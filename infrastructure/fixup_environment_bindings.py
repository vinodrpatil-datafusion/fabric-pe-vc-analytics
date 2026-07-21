"""Fabric environment-binding fixup (see deployment_pipelines.md).

Automates the manual remediation performed after every Dev -> Test/Prod
promotion so far. Promoting a Fabric item via Git sync (PR merge `dev` ->
`test`/`main`, each workspace's own Git integration pulling the merge in --
see deployment_pipelines.md's Git-driven promotion decision) only carries
item *definitions*. Anything a definition hardcodes about its own
environment -- a notebook's default-lakehouse metadata, a hardcoded
`abfss://` path, a DirectLake semantic model's data source connection
string -- still points at the *source* workspace after promotion, since
nothing about a plain file copy knows to rewrite environment-specific
identifiers. Six distinct instances of this were found and fixed by hand
across `pevc-test`/`pevc-prod` (notebook lakehouse bindings, hardcoded
notebook paths, the semantic model's DirectLake source); this script does
the same fixes programmatically.

**Same mechanism as Git integration itself, not a workaround** -- every
fix here is a `getDefinition` / `updateDefinition` REST call, the same API
surface Fabric's own Git sync uses to write these files. Driven by name
lookups (workspace names, lakehouse names, notebook names), not hardcoded
GUIDs, so this is reusable if a third non-Dev environment is ever added --
see deployment_pipelines.md's roadmap note on why that's worth doing rather
than repeating the manual fix a third time.

**What this does NOT do** (still manual, see deployment_pipelines.md):
uploading landing data into a fresh environment's `landing_lakehouse`, and
actually running the conformed/Gold notebooks there. This script only
fixes the bindings that would otherwise make those runs silently target
the wrong environment's storage.

Requires the signed-in identity (`az login`) to have Contributor-or-above
on the target workspace -- the same account that already has Fabric access
throughout this project (see ai-integration/agent_common.py's docstring for
the unrelated dual-identity situation that applies to the *other* leg of
this project, WS5's AI integration; this script only touches Fabric/OneLake
items under one identity).

Usage:
    pip install -r requirements.txt
    az login
    python fixup_environment_bindings.py --target pevc-test
    python fixup_environment_bindings.py --target pevc-prod --yes
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from dataclasses import dataclass
from typing import Any

import requests
from azure.identity import AzureCliCredential

FABRIC_API = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

NOTEBOOK_NAMES = [
    "01_schema_validation",
    "02_reconciliation",
    "03_bitemporal_load",
    "04_data_quality_assertions",
    "05_gold_star_schema",
]
LAKEHOUSE_NAMES = ["landing_lakehouse", "conformed_lakehouse", "gold_lakehouse"]
SEMANTIC_MODEL_NAME = "pevc-semantic-model"
POLL_INTERVAL_SECONDS = 5


def log(msg: str) -> None:
    print(f"[fixup_environment_bindings] {msg}")


# --- Fabric REST helpers ----------------------------------------------------

def fabric_get(token: str, path: str) -> dict:
    resp = requests.get(f"{FABRIC_API}{path}", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()


def fabric_post(token: str, path: str, body: dict | None = None) -> dict:
    """POST that transparently handles Fabric's long-running-operation pattern
    (202 + Location header, poll until Succeeded, fetch /result) alongside
    calls that just return 200 directly (e.g. refreshMetadata)."""
    resp = requests.post(
        f"{FABRIC_API}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body if body is not None else {},
    )
    if resp.status_code == 200:
        return resp.json() if resp.text else {}
    if resp.status_code != 202:
        resp.raise_for_status()

    op_url = resp.headers["Location"]
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        op = requests.get(op_url, headers={"Authorization": f"Bearer {token}"}).json()
        if op["status"] == "Succeeded":
            break
        if op["status"] == "Failed":
            raise RuntimeError(f"Fabric operation failed: {op}")

    result = requests.get(f"{op_url}/result", headers={"Authorization": f"Bearer {token}"})
    return result.json() if result.text else {}


def resolve_workspace_id(token: str, name: str) -> str:
    for w in fabric_get(token, "/workspaces")["value"]:
        if w["displayName"] == name:
            return w["id"]
    raise RuntimeError(f"Workspace '{name}' not found -- check the name and that the signed-in identity can see it.")


def resolve_items(token: str, workspace_id: str, item_type: str) -> dict[str, str]:
    """displayName -> id map for one item type in a workspace."""
    data = fabric_get(token, f"/workspaces/{workspace_id}/items?type={item_type}")
    return {i["displayName"]: i["id"] for i in data["value"]}


@dataclass
class Environment:
    name: str
    workspace_id: str
    lakehouse_ids: dict[str, str]  # lakehouse name -> id


def load_environment(token: str, name: str) -> Environment:
    ws_id = resolve_workspace_id(token, name)
    lakehouses = resolve_items(token, ws_id, "Lakehouse")
    missing = [n for n in LAKEHOUSE_NAMES if n not in lakehouses]
    if missing:
        raise RuntimeError(f"Workspace '{name}' is missing lakehouse(s): {missing}")
    return Environment(name=name, workspace_id=ws_id, lakehouse_ids=lakehouses)


# --- The fix itself: a GUID substitution map applied to text parts ---------
# Every one of the six gaps found by hand (notebook default_lakehouse
# metadata, notebook hardcoded abfss:// paths, the semantic model's
# DirectLake connection string) turned out to be the *same* source
# workspace/lakehouse GUIDs appearing as plain substrings in TMDL/notebook
# text -- so one blanket old-GUID -> new-GUID replacement across the
# relevant file fixes all of them, without needing separate JSON-parsing
# logic per gap type.

def build_substitution_map(source: Environment, target: Environment) -> dict[str, str]:
    mapping = {source.workspace_id: target.workspace_id}
    for lh_name, target_lh_id in target.lakehouse_ids.items():
        mapping[source.lakehouse_ids[lh_name]] = target_lh_id
    return mapping


def apply_substitutions(content: str, mapping: dict[str, str]) -> str:
    for old, new in mapping.items():
        content = content.replace(old, new)
    return content


def fix_item_definition(token: str, workspace_id: str, item_id: str, item_name: str,
                         mapping: dict[str, str], part_paths: set[str]) -> bool:
    """Fetches an item's definition, applies the GUID substitution map to the
    named text parts only (leaving every other part -- tables, relationships,
    measures, other code cells -- byte-for-byte untouched), and pushes back
    only if something actually changed. Returns whether a change was made."""
    definition = fabric_post(token, f"/workspaces/{workspace_id}/items/{item_id}/getDefinition")
    parts = definition["definition"]["parts"]
    changed = False

    for part in parts:
        if part["path"] not in part_paths:
            continue
        content = base64.b64decode(part["payload"]).decode("utf-8")
        new_content = apply_substitutions(content, mapping)
        if new_content != content:
            part["payload"] = base64.b64encode(new_content.encode("utf-8")).decode("ascii")
            changed = True

    if changed:
        fabric_post(token, f"/workspaces/{workspace_id}/items/{item_id}/updateDefinition",
                    {"definition": {"parts": parts}})
        log(f"  {item_name}: fixed")
    else:
        log(f"  {item_name}: no source-environment references found (already correct, or none present)")
    return changed


def fix_notebooks(token: str, source: Environment, target: Environment) -> None:
    notebooks = resolve_items(token, target.workspace_id, "Notebook")
    mapping = build_substitution_map(source, target)
    for name in NOTEBOOK_NAMES:
        if name not in notebooks:
            log(f"  WARNING: notebook '{name}' not found in {target.name}, skipping")
            continue
        fix_item_definition(token, target.workspace_id, notebooks[name], name, mapping, {"notebook-content.py"})


def fix_semantic_model(token: str, source: Environment, target: Environment) -> None:
    models = resolve_items(token, target.workspace_id, "SemanticModel")
    if SEMANTIC_MODEL_NAME not in models:
        log(f"  WARNING: semantic model '{SEMANTIC_MODEL_NAME}' not found in {target.name}, skipping")
        return
    mapping = build_substitution_map(source, target)
    fix_item_definition(token, target.workspace_id, models[SEMANTIC_MODEL_NAME], SEMANTIC_MODEL_NAME,
                         mapping, {"definition/expressions.tmdl"})


def refresh_sql_endpoints(token: str, target: Environment) -> None:
    for name, ep_id in resolve_items(token, target.workspace_id, "SQLEndpoint").items():
        fabric_post(token, f"/workspaces/{target.workspace_id}/sqlEndpoints/{ep_id}/refreshMetadata")
        log(f"  {name}: metadata refresh triggered")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="pevc-dev", help="Workspace everything was promoted from.")
    parser.add_argument("--target", required=True, choices=["pevc-test", "pevc-prod"],
                        help="Workspace to fix bindings in.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    token = AzureCliCredential().get_token(FABRIC_SCOPE).token

    log(f"Resolving '{args.source}' and '{args.target}' workspaces and lakehouses...")
    source = load_environment(token, args.source)
    target = load_environment(token, args.target)

    if not args.yes:
        reply = input(f"About to rewrite environment-specific bindings in '{args.target}' "
                       f"(workspace {target.workspace_id}) so they point at its own resources "
                       f"instead of '{args.source}'. This edits live notebook and semantic model "
                       f"definitions. Proceed? [y/N] ")
        if reply.strip().lower() != "y":
            log("Aborted.")
            return 1

    log("Fixing notebook lakehouse bindings + hardcoded paths...")
    fix_notebooks(token, source, target)

    log("Fixing semantic model DirectLake source...")
    fix_semantic_model(token, source, target)

    log("Refreshing SQL analytics endpoint metadata...")
    refresh_sql_endpoints(token, target)

    log(f"Done. '{args.target}' bindings now point at its own resources. Landing data upload and "
        f"notebook execution are still manual steps -- see deployment_pipelines.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
