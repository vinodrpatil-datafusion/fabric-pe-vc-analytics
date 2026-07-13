# Governance

This document describes the governance plane of the platform — access control, data sensitivity, lineage, and audit. It is the operational companion to the architectural treatment in [`architecture.md`](architecture.md) Section 4.

---

## 1. Access control layers

Five layers, each enforced independently. Defence in depth — a failure at one layer is mitigated by the others.

### Layer 1: Tenant-level

- Fabric tenant admin controls who can create workspaces, allocate capacity, and configure tenant-wide settings.
- For a multi-customer production deployment, tenant separation would be the outer-most isolation boundary.

### Layer 2: Domain-level

- The `Investment Analytics` domain groups all workspaces in this platform.
- Domain admin manages cross-workspace settings without granting access to individual workspace contents.
- In an institutional context, domain-level governance separates the investment data estate from other data estates (HR, finance, operations).

### Layer 3: Workspace-level (target design)

In the production-target layout (DD-10), each workspace has admin, member, and viewer
roles; cross-workspace access is explicit (shortcut-based read, never implicit
promotion); workspace boundaries align with data quality boundaries (ingestion,
conformed, serving). **At trial scope (DD-14), this layer collapses to one workspace**
(`pevc-dev`) with a single admin — the workspace-level boundary isn't doing governance
work here, since there's nothing to separate a second workspace from. Layer 4 carries
the boundary instead.

### Layer 4: Item-level

- Lakehouses, Warehouses, semantic models, notebooks have item-level RBAC.
- Granular access for sensitive items (internal deal pipeline data) is enforced at this level.
- **At trial scope, this is the layer actually enforcing the data-quality boundary**
  (landing vs. conformed vs. serving) that Layer 3 would carry in the target design —
  each lakehouse/notebook is a distinct item within `pevc-dev`, even though they share
  a workspace.

### Layer 5: Data-level

- DAX-level security in semantic models for analyst-segmented dashboards.
- Row-level security in Warehouse views is the documented pattern if Warehouse serving
  is ever reopened (see [`design_decisions.md`](design_decisions.md) DD-05) — not built
  at portfolio scope, since no Warehouse is provisioned.
- Sensitivity-label-based filtering for AI retrieval (documents above an analyst's clearance never enter retrieval context).

---

## 2. Sensitivity classification

Microsoft Purview sensitivity labels are applied at the table or column level in the conformed layer and propagate through OneLake to all consumers.

Label taxonomy (illustrative; would be customised per institution):

| Label | Definition | Example |
|---|---|---|
| Public | Information already disclosed publicly | Announced funding rounds, public company data |
| Internal | Internal-use information without external sensitivity | Internal sector classifications, analyst-generated tags |
| Confidential | Information subject to NDA or competitive sensitivity | Internal deal pipeline records, IC memo content |
| Restricted | Information subject to regulatory or contractual restrictions | LP relationships, certain regulated jurisdictions data |

Labels are immutable once applied; reclassification requires explicit governance approval and audit trail.

---

## 3. Lineage

End-to-end lineage is designed around Microsoft Purview integration with Fabric.
**Status:** designed, not yet wired up in the trial tenant — this section describes the
target lineage model (see also the README roadmap).

### Data lineage

Tracked automatically:
- Source (external storage, internal database) → landing Lakehouse (via shortcut)
- Landing → conformed (via notebooks and pipelines)
- Conformed → serving (via shortcuts)
- Serving → BI reports and AI responses

Queryable via Purview UI and API. Compliance and engineering both have access.

### Inference lineage

Tracked through a custom inference audit table — target design names it
`ws-serving-ai-dev/inference_audit`; as-built (DD-14) it would be `pevc-dev/
inference_audit` once the AI serving layer (DD-13, not yet built) exists:

| Captured | Purpose |
|---|---|
| Prompt template version | Reproducibility |
| Model version (Azure OpenAI deployment) | Reproducibility |
| Retrieval context hash | Reproducibility |
| User identifier | Audit |
| Timestamp | Audit |
| Response | Audit and quality review |
| Validation status (schema, citations) | Quality monitoring |
| User action (accepted, modified, overridden) | Feedback loop |

Future-state: integrate inference lineage with Purview when Fabric AI lineage support extends to Azure OpenAI integrations.

---

## 4. Audit substrates

Three independent audit logs:

### 4.1 Data access audit

Native Fabric auditing logs read/write access to Lakehouse and Warehouse items. Queryable via Fabric admin portal and audit log API.

Retention: 90 days hot; longer-term retention via export to dedicated storage.

### 4.2 Inference audit

Custom audit table as described in Section 3 (inference lineage). Append-only Delta table — `pevc-dev` as-built once built (DD-14); `ws-serving-ai-dev` in the target design.

Retention: indefinite for high-stakes outputs (IC memo support); sampled or aggregated for lower-stakes.

### 4.3 Decision audit

For BI consumers, Power BI usage metrics track report views, exports, and shares.

For AI consumers, the inference audit table captures `user_action` (accepted, modified, overridden) as a downstream signal.

Both feed into a unified decision audit view (Lakehouse SQL endpoint at portfolio scope; a Warehouse view if that serving path is reopened — see DD-05) for analyst behaviour reporting and feedback loop sourcing.

---

## 5. Reconciliation transparency

Beyond formal audit, the reconciliation log (`conformed_lakehouse.reconciliation_log` — see [`data_model.md`](data_model.md) Section 1.8) provides analyst-visible transparency on data quality conflicts.

An analyst querying a company can see:
- Which sources contributed to the current record
- Where sources disagreed and how the disagreement was resolved
- When the resolution occurred and who or what made it

This is governance as usability: making the data quality process visible builds the trust that allows analysts to act on platform outputs.

---

## 6. What this design defers

For a production deployment, the following extend the governance design but are not implemented at portfolio scope:

- **Customer-managed encryption keys** — OneLake supports them; portfolio uses default Microsoft-managed keys.
- **Cross-region data residency controls** — single-region implementation; multi-region adds complexity beyond portfolio scope.
- **Formal data classification automation** — labels are applied manually; production would use Purview's automatic classification.
- **DLP integration** — for outbound prevention of sensitive data; portfolio scope assumes a controlled environment.

---

*Last updated: 2026-07-13.*
