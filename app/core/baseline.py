"""
baseline.py – Computes per-entity baselines from same-weekday historical values.

For each (entity_id, metric), takes the previous N same-weekday values, computes:
  • baseline  = median
  • spread    = scaled MAD (or std when n == 4)
  • n_history = number of history points used

Entities with < MIN_HISTORY points are skipped and returned in a separate list.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from app.config import MIN_HISTORY


def compute_baselines(
    long_df: pd.DataFrame,
    target_date: date,
    n_weeks: int = 4,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Parameters
    ----------
    long_df     : normalised long-format DataFrame
    target_date : the day being analysed
    n_weeks     : how many same-weekday prior values to use

    Returns
    -------
    (analysis_df, skipped_entities)

    analysis_df has columns:
        date, system, entity_type, entity_id, metric, value,
        baseline, spread, n_history, pct_change, z
    """
    target_weekday = target_date.weekday()   # 0=Mon … 6=Sun

    # Split target from history
    long_df = long_df.copy()
    long_df["date"] = pd.to_datetime(long_df["date"]).dt.date

    target_rows = long_df[long_df["date"] == target_date].copy()
    hist_rows   = long_df[long_df["date"] != target_date].copy()

    # Keep only same-weekday rows in history
    hist_rows["weekday"] = pd.to_datetime(hist_rows["date"]).dt.weekday
    same_wd = hist_rows[hist_rows["weekday"] == target_weekday].copy()

    # For each entity+metric, pick the most recent n_weeks values
    same_wd = (
        same_wd.sort_values("date", ascending=False)
        .groupby(["entity_id", "metric"], as_index=False)
        .head(n_weeks)
    )

    # Compute baseline stats
    def _stats(grp: pd.DataFrame) -> pd.Series:
        vals = grp["value"].dropna().values
        n    = len(vals)
        if n == 0:
            return pd.Series({"baseline": np.nan, "spread": np.nan, "n_history": 0})
        med = float(np.median(vals))
        if n >= 2:
            mad = float(np.median(np.abs(vals - med)))
            spread = mad * 1.4826 if mad > 0 else float(np.std(vals, ddof=1))
        else:
            spread = 0.0
        return pd.Series({"baseline": med, "spread": spread, "n_history": n})

    baseline_stats = (
        same_wd.groupby(["entity_id", "metric"])
        .apply(_stats)
        .reset_index()
    )

    # Merge onto target rows
    result = target_rows.merge(baseline_stats, on=["entity_id", "metric"], how="left")

    skipped: list[str] = []

    # Compute pct_change and z-score
    def _pct_z(row: pd.Series):
        b = row["baseline"]
        s = row["spread"]
        v = row["value"]
        n = row.get("n_history", 0)

        if pd.isna(b) or n < MIN_HISTORY:
            return pd.Series({"pct_change": np.nan, "z": np.nan})

        pct = (v - b) / b if b != 0 else np.nan
        z   = (v - b) / s if s and s > 0 else np.nan
        return pd.Series({"pct_change": pct, "z": z})

    pct_z = result.apply(_pct_z, axis=1)
    result = pd.concat([result, pct_z], axis=1)

    # Collect skipped (insufficient history)
    low_hist = result[result["n_history"] < MIN_HISTORY]
    for _, row in low_hist.iterrows():
        skipped.append(f"{row['entity_id']} / {row['metric']} (n={row.get('n_history', 0)})")

    result = result[result["n_history"] >= MIN_HISTORY]
    return result, skipped


if __name__ == "__main__":
    from datetime import date as dt
    from ingest import ingest
    from normalize import normalize

    dfs, _ = ingest()
    long   = normalize(dfs, dt(2026, 10, 10))
    df, sk = compute_baselines(long, dt(2026, 10, 10))
    print(df[df["entity_id"] == "Station X"][["entity_id", "metric", "value",
                                               "baseline", "pct_change", "z"]])
    print(f"\nSkipped entities: {len(sk)}")
