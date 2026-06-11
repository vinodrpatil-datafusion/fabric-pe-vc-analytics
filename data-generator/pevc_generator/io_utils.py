"""Output helpers.

Landing feeds are written as Parquet when pyarrow is available, else CSV.
Nested attributes (arrays, structs) are serialized as JSON strings — this
mirrors how raw vendor feeds actually deliver nested data, and the conformed
layer (WS2) parses them. Dates are ISO strings for CSV friendliness.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd


def has_pyarrow() -> bool:
    return importlib.util.find_spec("pyarrow") is not None


PREFER_PARQUET = has_pyarrow()
OUTPUT_EXT = "parquet" if PREFER_PARQUET else "csv"


def write_table(df: pd.DataFrame, out_dir: Path, name: str, json_cols: list[str] | None = None) -> Path:
    """Write a DataFrame, serializing json_cols to JSON strings first."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    for c in (json_cols or []):
        if c in df.columns:
            df[c] = df[c].apply(lambda v: None if v is None else json.dumps(v, default=str))
    if PREFER_PARQUET:
        p = out_dir / f"{name}.parquet"
        df.to_parquet(p, index=False)
    else:
        p = out_dir / f"{name}.csv"
        df.to_csv(p, index=False)
    return p


def read_table(path_no_ext: Path) -> pd.DataFrame:
    """Read a table by base path, trying parquet then csv."""
    pq = path_no_ext.with_suffix(".parquet")
    csv = path_no_ext.with_suffix(".csv")
    if pq.exists():
        return pd.read_parquet(pq)
    if csv.exists():
        return pd.read_csv(csv)
    raise FileNotFoundError(f"Neither {pq} nor {csv} exists")
