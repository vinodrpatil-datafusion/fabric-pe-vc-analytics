"""PE/VC synthetic data generator for Fabric Lakehouse ingestion."""

from .lineage import LINEAGE_COLUMNS, LineageContext, attach_lineage
from .scale import LARGE, MEDIUM, PROFILES, SMALL, ScaleProfile

__all__ = [
    "LineageContext",
    "attach_lineage",
    "LINEAGE_COLUMNS",
    "ScaleProfile",
    "SMALL",
    "MEDIUM",
    "LARGE",
    "PROFILES",
]
