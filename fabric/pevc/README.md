# Fabric Git integration sync folder — `pevc-dev`

This folder is the connection target for `pevc-dev`'s Fabric Git integration
(Workspace settings → Git integration → GitHub → folder `fabric/pevc-dev`).

**Do not hand-author files here.** Fabric populates this folder itself — each
workspace item (lakehouse, notebook, etc.) becomes its own subfolder with a
`.platform` file carrying the item's `logicalId`, which is how Fabric's sync
engine matches a Git folder back to the correct existing workspace item.
Files written by anything other than Fabric's own **Commit** operation won't
carry a valid `logicalId` and risk creating duplicate items on sync instead of
linking to what's already in the workspace.

**Bootstrap step (one-time):** since `pevc-dev` already has content (3
lakehouses, 5 notebooks) and this folder starts empty, the first sync must be
a **Commit** (workspace → Git) from the Fabric portal's Source control pane —
not an Update (Git → workspace).

**Relationship to `notebooks/*.ipynb`:** those files are a separate,
human-readable working copy maintained by hand in this repo. They are not
the same files Fabric syncs here (Fabric exports notebooks as
`<name>.Notebook/notebook-content.py`, not `.ipynb`), and the two are not
auto-synced with each other — changes made in one still need to be
manually ported to the other.
