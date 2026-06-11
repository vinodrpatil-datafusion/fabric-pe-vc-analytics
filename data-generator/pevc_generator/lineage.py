"""Lineage metadata for synthetic PE/VC data.

Every entity row carries these columns so Bronze→Silver→Gold promotion
preserves provenance, and Purview classification has surface to attach to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

DATA_VERSION = "v1.0.0"
SOURCE_SYSTEM = "pevc-synthetic-generator"


@dataclass(frozen=True)
class LineageContext:
    """Per-run lineage context. One instance per generator invocation."""

    batch_id: str
    ingestion_ts: datetime
    data_version: str = DATA_VERSION
    source_system: str = SOURCE_SYSTEM

    @classmethod
    def new(cls) -> "LineageContext":
        return cls(
            batch_id=str(uuid.uuid4()),
            ingestion_ts=datetime.now(timezone.utc),
        )


def attach_lineage(
    df: pd.DataFrame,
    ctx: LineageContext,
    source_file: str,
) -> pd.DataFrame:
    """Add lineage columns to a DataFrame in place-safe manner.

    Columns added (prefixed with `_` to mark as metadata, not business data):
        _record_id        per-row UUID
        _source_system    fixed identifier
        _source_file      output filename for this entity
        _ingestion_ts     run timestamp (UTC)
        _batch_id         run identifier
        _data_version     schema version
        _is_synthetic     always True — explicit honesty flag
    """
    out = df.copy()
    out["_record_id"] = [str(uuid.uuid4()) for _ in range(len(out))]
    out["_source_system"] = ctx.source_system
    out["_source_file"] = source_file
    out["_ingestion_ts"] = ctx.ingestion_ts
    out["_batch_id"] = ctx.batch_id
    out["_data_version"] = ctx.data_version
    out["_is_synthetic"] = True
    return out


LINEAGE_COLUMNS = [
    "_record_id",
    "_source_system",
    "_source_file",
    "_ingestion_ts",
    "_batch_id",
    "_data_version",
    "_is_synthetic",
]
