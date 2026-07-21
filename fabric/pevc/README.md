# Fabric Git integration sync folder — shared across all three environments

This folder (`fabric/pevc/`) is the connection target for **all three** environment
workspaces' Fabric Git integration, one per branch:

| Workspace | Branch | Git folder |
|---|---|---|
| `pevc-dev` | `dev` | `fabric/pevc` |
| `pevc-test` | `test` | `fabric/pevc` |
| `pevc-prod` | `main` | `fabric/pevc` |

The path is deliberately **identical on every branch** — see
[`../../infrastructure/deployment_pipelines.md`](../../infrastructure/deployment_pipelines.md)
for why: promotion between environments is a plain PR merge (`dev` → `test` → `main`),
and a matching folder path across branches is what makes that a normal git merge
instead of a same-PR rename. The folder was originally named `fabric/pevc-dev/`
(environment-specific) before `pevc-test`/`pevc-prod` existed; it was renamed
environment-neutral before either of those workspaces was ever connected.

**Do not hand-author files here.** Fabric populates this folder itself — each
workspace item (lakehouse, notebook, semantic model, report) becomes its own subfolder
with a `.platform` file carrying the item's `logicalId`, which is how Fabric's sync
engine matches a Git folder back to the correct existing workspace item. Files written
by anything other than Fabric's own **Commit** operation won't carry a valid
`logicalId` and risk creating duplicate items on sync instead of linking to what's
already in the workspace.

**Promotion is Git-driven, not the Fabric deployment pipeline's Deploy button** — see
DD-12's revisions in [`../../docs/design_decisions.md`](../../docs/design_decisions.md).
A promoted item's *definition* (this folder's content) is not the whole story: notebook
lakehouse bindings, hardcoded `abfss://` paths, and the semantic model's DirectLake data
source all still need fixing up per environment after a Git sync, since none of that is
environment-portable by nature. See `../../infrastructure/fixup_environment_bindings.py`
— it automates exactly that.

**Relationship to `notebooks/*.ipynb`:** those files are a separate, human-readable
working copy maintained by hand in this repo. They are not the same files Fabric syncs
here (Fabric exports notebooks as `<name>.Notebook/notebook-content.py`, not `.ipynb`),
and the two are not auto-synced with each other — changes made in one still need to be
manually ported to the other.
