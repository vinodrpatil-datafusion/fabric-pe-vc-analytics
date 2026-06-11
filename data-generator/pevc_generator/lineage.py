"""Landing-layer lineage metadata.

At the landing layer, rows carry raw ingestion provenance only. The conformed
bitemporal columns (effective_date, ingestion_date, source_attribution,
reconciliation_status) are assigned by WS2's conformed load — NOT here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

DATA_VERSION = "v2.0.0"


@dataclass(frozen=True)
class LineageContext:
    batch_id: str
    ingestion_ts: datetime
    data_version: str = DATA_VERSION

    @classmethod
    def new(cls) -> "LineageContext":
        return cls(batch_id=str(uuid.uuid4()), ingestion_ts=datetime.now(timezone.utc))


def attach_landing_lineage(
    df: pd.DataFrame,
    ctx: LineageContext,
    source_system: str,
    source_file: str,
) -> pd.DataFrame:
    """Add landing metadata columns (prefixed `_`)."""
    out = df.copy()
    out["_record_id"] = [str(uuid.uuid4()) for _ in range(len(out))]
    out["_source_system"] = source_system
    out["_source_file"] = source_file
    out["_ingestion_ts"] = ctx.ingestion_ts.isoformat()
    out["_batch_id"] = ctx.batch_id
    out["_data_version"] = ctx.data_version
    out["_is_synthetic"] = True
    return out


LANDING_LINEAGE_COLUMNS = [
    "_record_id", "_source_system", "_source_file",
    "_ingestion_ts", "_batch_id", "_data_version", "_is_synthetic",
]
