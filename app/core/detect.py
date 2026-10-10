"""
detect.py – Applies anomaly detection rules and ranks exceptions.

Rules (all configurable in config.py):
    1. Ridership shift   : |pct_change| >= PCT_THRESHOLD AND |z| >= Z_THRESHOLD
    2. Service delivery  : trips_ratio < TRIPS_RATIO threshold
    3. Breakdown spike   : breakdowns >= BREAKDOWN_MUL * baseline AND >= 2
    4. Gate downtime     : gate_downtime_min >= GATE_MIN

Severity score = weighted combination of |pct_change|, absolute riders affected,
and rule type priority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from app.config import (PCT_THRESHOLD, Z_THRESHOLD, TRIPS_RATIO,
                    BREAKDOWN_MUL, GATE_MIN, TOP_N)

SEVERITY_LABELS = {3: "High", 2: "Medium", 1: "Low"}


@dataclass
class Exception_:
    """Represents one detected anomaly before cause/narrative enrichment."""
    entity_id:    str
    system:       str
    entity_type:  str
    metric:       str
    value:        float
    baseline:     float
    pct_change:   float       # fractional, e.g. -0.12
    z:            float
    rule:         str         # 'ridership' | 'trips_ratio' | 'breakdown' | 'gate'
    severity:     str         # 'High' | 'Medium' | 'Low'
    severity_score: float
    direction:    str         # 'up' | 'down'
    riders_affected: float = 0.0   # estimated ridership delta (absolute)
    # Filled in by causes.py / narrate.py
    cause_category: str = "unknown"
    cause_label:  str = ""
    confidence:   str = ""
    evidence:     list[str] = field(default_factory=list)
    narrative:    str = ""
    narrative_source: str = ""   # 'template' | 'llm'
    # Recurrence fields
    owner: str = ""
    action: str = ""
    recurrence_count: int = 1
    recurrence_label: str = ""
    original_severity: str = ""
    past_dates: list[str] = field(default_factory=list)


def _severity_score(pct: float, riders: float, rule_priority: int) -> float:
    """Composite score for ranking; higher = more severe."""
    return abs(pct) * 40 + (riders / 1000) * 20 + rule_priority * 10


def _severity_label(score: float) -> str:
    if score >= 60:
        return "High"
    elif score >= 30:
        return "Medium"
    return "Low"


def detect(
    analysis_df: pd.DataFrame,
    dfs: dict,
    target_date: date,
    top_n: int = TOP_N,
) -> tuple[list[Exception_], list[Exception_]]:
    """
    Parameters
    ----------
    analysis_df : output from baseline.compute_baselines()
    dfs         : raw ingested dataframes (for gate downtime lookup)
    target_date : the target day
    top_n       : max exceptions to return in the main list

    Returns
    -------
    (top_exceptions, overflow_exceptions)
    """
    exceptions: list[Exception_] = []

    # ── Rule 1: Ridership shift ───────────────────────────────────────────────
    rid = analysis_df[analysis_df["metric"] == "ridership"].copy()
    rid = rid.dropna(subset=["pct_change", "z"])
    mask = (rid["pct_change"].abs() >= PCT_THRESHOLD) & (rid["z"].abs() >= Z_THRESHOLD)
    for _, row in rid[mask].iterrows():
        pct   = float(row["pct_change"])
        riders = abs(float(row["value"]) - float(row["baseline"]))
        score = _severity_score(pct, riders, 3)
        exceptions.append(Exception_(
            entity_id=row["entity_id"],
            system=row["system"],
            entity_type=row["entity_type"],
            metric="ridership",
            value=float(row["value"]),
            baseline=float(row["baseline"]),
            pct_change=pct,
            z=float(row["z"]),
            rule="ridership",
            severity=_severity_label(score),
            severity_score=score,
            direction="up" if pct > 0 else "down",
            riders_affected=riders,
        ))

    # ── Rule 2: Service delivery (trips ratio) ────────────────────────────────
    tr = analysis_df[analysis_df["metric"] == "trips_ratio"].copy()
    tr = tr.dropna(subset=["value"])
    for _, row in tr[tr["value"] < TRIPS_RATIO].iterrows():
        pct   = float(row["value"]) - 1.0    # negative
        score = _severity_score(pct, 500, 2)  # no direct ridership count
        exceptions.append(Exception_(
            entity_id=row["entity_id"],
            system=row["system"],
            entity_type=row["entity_type"],
            metric="trips_ratio",
            value=float(row["value"]),
            baseline=float(row.get("baseline", 1.0)) if not pd.isna(row.get("baseline")) else 1.0,
            pct_change=pct,
            z=float(row["z"]) if not pd.isna(row.get("z")) else 0.0,
            rule="trips_ratio",
            severity=_severity_label(abs(score)),
            severity_score=abs(score),
            direction="down",
        ))

    # ── Rule 3: Breakdown spike ───────────────────────────────────────────────
    bd = analysis_df[analysis_df["metric"] == "breakdowns"].copy()
    bd = bd.dropna(subset=["value"])
    for _, row in bd.iterrows():
        v = float(row["value"])
        b = float(row["baseline"]) if not pd.isna(row.get("baseline")) else 0
        if v >= max(2, BREAKDOWN_MUL * b) and v >= 2:
            pct   = (v - b) / b if b > 0 else 1.0
            score = _severity_score(pct, 300, 2)
            exceptions.append(Exception_(
                entity_id=row["entity_id"],
                system=row["system"],
                entity_type=row["entity_type"],
                metric="breakdowns",
                value=v,
                baseline=b,
                pct_change=pct,
                z=float(row["z"]) if not pd.isna(row.get("z")) else 0.0,
                rule="breakdown",
                severity=_severity_label(score),
                severity_score=score,
                direction="up",
            ))

    # ── Rule 4: Gate downtime ─────────────────────────────────────────────────
    gt = analysis_df[analysis_df["metric"] == "gate_downtime_min"].copy()
    gt = gt.dropna(subset=["value"])
    for _, row in gt[gt["value"] >= GATE_MIN].iterrows():
        v     = float(row["value"])
        score = _severity_score(0.2, 1000, 3) + (v / 60) * 5
        exceptions.append(Exception_(
            entity_id=row["entity_id"],
            system=row["system"],
            entity_type=row["entity_type"],
            metric="gate_downtime_min",
            value=v,
            baseline=float(row["baseline"]) if not pd.isna(row.get("baseline")) else 0,
            pct_change=0.0,
            z=0.0,
            rule="gate",
            severity=_severity_label(score),
            severity_score=score,
            direction="up",
        ))

    # De-duplicate: if same entity has both 'gate' and 'ridership', keep both
    # but de-dup identical (entity, metric) pairs
    seen = set()
    deduped = []
    for ex in exceptions:
        key = (ex.entity_id, ex.metric)
        if key not in seen:
            seen.add(key)
            deduped.append(ex)

    # Sort by severity score descending
    deduped.sort(key=lambda x: x.severity_score, reverse=True)

    top      = deduped[:top_n]
    overflow = deduped[top_n:]
    return top, overflow


if __name__ == "__main__":
    from datetime import date as dt
    from ingest import ingest
    from normalize import normalize
    from baseline import compute_baselines

    dfs, rpt  = ingest()
    long      = normalize(dfs, dt(2026, 10, 10))
    analysis, sk = compute_baselines(long, dt(2026, 10, 10))
    top, over = detect(analysis, dfs, dt(2026, 10, 10))
    print(f"Top exceptions ({len(top)}):")
    for ex in top:
        print(f"  [{ex.severity}] {ex.entity_id} / {ex.metric}: "
              f"{ex.pct_change*100:+.1f}%  (z={ex.z:.2f})")
    print(f"\nOverflow: {len(over)} more exceptions")
