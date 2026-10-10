"""
normalize.py – Converts all source dataframes to a common long format.

Output schema:
    date | system | entity_type | entity_id | metric | value
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd


def normalize(
    dfs: dict[str, Optional[pd.DataFrame]],
    target_date: date,
) -> pd.DataFrame:
    """
    Converts each source dataframe into the common long format and concatenates.

    Parameters
    ----------
    dfs : output from ingest.ingest()
    target_date : the day being analysed

    Returns
    -------
    DataFrame with columns: date, system, entity_type, entity_id, metric, value
    """
    frames: list[pd.DataFrame] = []

    # ── Metro: ridership (sum over hour_bands) ────────────────────────────────
    if dfs.get("metro_daily") is not None:
        md = dfs["metro_daily"].copy()
        # Aggregate hour bands → daily totals per station
        agg = (
            md.groupby(["date", "station"], as_index=False)
            .agg(
                entries=("entries", "sum"),
                exits=("exits", "sum"),
                gate_downtime_min=("gate_downtime_min", "sum"),
            )
        )
        # Ridership = entries
        frames.append(_melt_single(agg, "METRO", "station", "station",
                                   "entries", "ridership"))
        # Gate downtime
        frames.append(_melt_single(agg, "METRO", "station", "station",
                                   "gate_downtime_min", "gate_downtime_min"))

    # ── BRTS ─────────────────────────────────────────────────────────────────
    if dfs.get("brts_daily") is not None:
        bd = dfs["brts_daily"].copy()
        bd["trips_ratio"] = bd["trips_run"] / bd["trips_planned"].replace(0, pd.NA)
        frames.append(_melt_single(bd, "BRTS", "route", "route",
                                   "boardings",   "ridership"))
        frames.append(_melt_single(bd, "BRTS", "route", "route",
                                   "trips_ratio", "trips_ratio"))
        frames.append(_melt_single(bd, "BRTS", "route", "route",
                                   "breakdowns",  "breakdowns"))

    # ── AMTS ─────────────────────────────────────────────────────────────────
    if dfs.get("amts_daily") is not None:
        ad = dfs["amts_daily"].copy()
        ad["trips_ratio"] = ad["trips_run"] / ad["trips_planned"].replace(0, pd.NA)
        frames.append(_melt_single(ad, "AMTS", "route", "route",
                                   "boardings",   "ridership"))
        frames.append(_melt_single(ad, "AMTS", "route", "route",
                                   "trips_ratio", "trips_ratio"))
        frames.append(_melt_single(ad, "AMTS", "route", "route",
                                   "breakdowns",  "breakdowns"))

    if not frames:
        return pd.DataFrame(columns=["date", "system", "entity_type",
                                     "entity_id", "metric", "value"])

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.dropna(subset=["value"])
    return df


def _melt_single(
    df: pd.DataFrame,
    system: str,
    entity_col: str,
    entity_type: str,
    value_col: str,
    metric: str,
) -> pd.DataFrame:
    """Helper: extract one metric column into the long format."""
    out = df[["date", entity_col, value_col]].copy()
    out.columns = ["date", "entity_id", "value"]
    out["system"]      = system
    out["entity_type"] = entity_type
    out["metric"]      = metric
    return out[["date", "system", "entity_type", "entity_id", "metric", "value"]]


if __name__ == "__main__":
    from datetime import date as dt
    from ingest import ingest
    dfs, _ = ingest()
    long = normalize(dfs, dt(2026, 10, 10))
    print(long.head(10))
    print(f"\nTotal rows: {len(long)}")
