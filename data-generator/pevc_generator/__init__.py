"""PE/VC investment-analytics synthetic data generator (v2).

Generates raw multi-source landing feeds aligned to data_model.md, with
controlled conflicts for the conformed-layer reconciliation (WS2).
"""

from .lineage import LANDING_LINEAGE_COLUMNS, LineageContext, attach_landing_lineage
from .scale import LARGE, MEDIUM, PROFILES, SMALL, ScaleProfile

__all__ = [
    "LineageContext", "attach_landing_lineage", "LANDING_LINEAGE_COLUMNS",
    "ScaleProfile", "SMALL", "MEDIUM", "LARGE", "PROFILES",
]
