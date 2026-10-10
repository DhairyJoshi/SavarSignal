"""
ingest.py – Reads and validates the six CSVs.
Returns (dataframes_dict, DataQualityReport).
Missing files or bad values are recorded, never raised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from app.config import DATA_DIR, METRO_DAILY_CSV, METRO_INCIDENTS_CSV, \
    BRTS_DAILY_CSV, AMTS_DAILY_CSV, WEATHER_CSV, EVENTS_CSV

# ── Schema definitions ────────────────────────────────────────────────────────
SCHEMAS: dict[str, dict] = {
    "metro_daily": {
        "required_cols": ["date", "station", "hour_band", "entries", "exits", "gate_downtime_min"],
        "non_negative":  ["entries", "exits", "gate_downtime_min"],
    },
    "metro_incidents": {
        "required_cols": ["date", "station", "type", "duration_min"],
        "non_negative":  ["duration_min"],
    },
    "brts_daily": {
        "required_cols": ["date", "route", "trips_planned", "trips_run", "boardings", "breakdowns"],
        "non_negative":  ["trips_planned", "trips_run", "boardings", "breakdowns"],
    },
    "amts_daily": {
        "required_cols": ["date", "route", "trips_planned", "trips_run", "boardings", "breakdowns"],
        "non_negative":  ["trips_planned", "trips_run", "boardings", "breakdowns"],
    },
    "weather": {
        "required_cols": ["date", "rainfall_mm", "max_temp_c"],
        "non_negative":  ["rainfall_mm"],
    },
    "events": {
        "required_cols": ["date", "name", "venue", "nearest_station", "expected_attendance"],
        "non_negative":  ["expected_attendance"],
    },
}


@dataclass
class DataQualityReport:
    missing_files: list[str] = field(default_factory=list)
    missing_columns: dict[str, list[str]] = field(default_factory=dict)
    invalid_values: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.missing_files or self.missing_columns or
                    self.invalid_values or self.warnings)

    def summary_lines(self) -> list[str]:
        lines = []
        for f in self.missing_files:
            lines.append(f"⚠ Missing file: {f}")
        for src, cols in self.missing_columns.items():
            lines.append(f"⚠ {src}: missing columns {cols}")
        for src, errs in self.invalid_values.items():
            for e in errs:
                lines.append(f"⚠ {src}: {e}")
        for w in self.warnings:
            lines.append(f"ℹ {w}")
        return lines


def _read_csv(path: str, key: str, report: DataQualityReport) -> Optional[pd.DataFrame]:
    """Read and validate one CSV. Returns None if the file is missing."""
    if not os.path.exists(path):
        report.missing_files.append(os.path.basename(path))
        return None

    df = pd.read_csv(path)
    schema = SCHEMAS[key]

    # Column check
    missing = [c for c in schema["required_cols"] if c not in df.columns]
    if missing:
        report.missing_columns[key] = missing

    # Date parsing
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        bad_dates = df["date"].isna().sum()
        if bad_dates:
            report.invalid_values.setdefault(key, []).append(
                f"{bad_dates} unparseable date value(s)")
        df = df.dropna(subset=["date"])

    # Non-negative check
    for col in schema.get("non_negative", []):
        if col in df.columns:
            neg = (df[col] < 0).sum()
            if neg:
                report.invalid_values.setdefault(key, []).append(
                    f"{neg} negative value(s) in column '{col}'")
                df = df[df[col] >= 0]

    # Duplicate check
    dedup_cols = [c for c in schema["required_cols"] if c in df.columns and c != "date"]
    if dedup_cols and "date" in df.columns:
        dupes = df.duplicated(subset=["date"] + dedup_cols[:2]).sum()
        if dupes:
            report.warnings.append(f"{key}: {dupes} duplicate row(s) dropped")
            df = df.drop_duplicates(subset=["date"] + dedup_cols[:2])

    return df


def ingest(data_dir: str = DATA_DIR) -> tuple[dict[str, Optional[pd.DataFrame]], DataQualityReport]:
    """
    Reads all six CSVs from *data_dir*.
    Returns a dict keyed by source name and a DataQualityReport.
    """
    report = DataQualityReport()
    files = {
        "metro_daily":     (METRO_DAILY_CSV,     data_dir),
        "metro_incidents": (METRO_INCIDENTS_CSV,  data_dir),
        "brts_daily":      (BRTS_DAILY_CSV,       data_dir),
        "amts_daily":      (AMTS_DAILY_CSV,       data_dir),
        "weather":         (WEATHER_CSV,           data_dir),
        "events":          (EVENTS_CSV,            data_dir),
    }
    dfs: dict[str, Optional[pd.DataFrame]] = {}
    for key, (fname, directory) in files.items():
        path = os.path.join(directory, fname)
        dfs[key] = _read_csv(path, key, report)

    return dfs, report


if __name__ == "__main__":
    dfs, rpt = ingest()
    for k, df in dfs.items():
        print(f"{k}: {len(df) if df is not None else 'MISSING'} rows")
    if rpt.has_issues:
        print("\nData quality issues:")
        for line in rpt.summary_lines():
            print(" ", line)
    else:
        print("\nAll files OK.")
