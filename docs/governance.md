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

### Layer 3: Workspace-level

- Each workspace has admin, member, and viewer roles.
- Cross-workspace access is explicit — shortcut-based read, never implicit promotion.
- Workspace boundaries align with data quality boundaries (ingestion, conformed, serving).

### Layer 4: Item-level

- Lakehouses, Warehouses, semantic models, notebooks have item-level RBAC.
- Granular access for sensitive items (internal deal pipeline data) is enforced at this level.

### Layer 5: Data-level

- Row-level security in Warehouse views for tenant-scoped or analyst-scoped data.
- DAX-level security in semantic models for analyst-segmented dashboards.
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

End-to-end lineage is captured through Microsoft Purview integration with Fabric.

### Data lineage

Tracked automatically:
- Source (external storage, internal database) → landing Lakehouse (via shortcut)
- Landing → conformed (via notebooks and pipelines)
- Conformed → serving (via shortcuts)
- Serving → BI reports and AI responses

Queryable via Purview UI and API. Compliance and engineering both have access.

### Inference lineage

Tracked through a custom inference audit table (`ws-serving-ai-dev/inference_audit`):

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

Custom audit table as described in Section 3 (inference lineage). Append-only Delta table in `ws-serving-ai-dev`.

Retention: indefinite for high-stakes outputs (IC memo support); sampled or aggregated for lower-stakes.

### 4.3 Decision audit

For BI consumers, Power BI usage metrics track report views, exports, and shares.

For AI consumers, the inference audit table captures `user_action` (accepted, modified, overridden) as a downstream signal.

Both feed into a unified decision audit view in the Warehouse for analyst behaviour reporting and feedback loop sourcing.

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

*Last updated: May 2026.*
