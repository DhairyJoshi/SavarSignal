"""
causes.py – Evidence collection and cause suggestion for each exception.

Evidence rules (ordered by confidence):
    1. Gate/lift/signal incident at same station+day  → "Gate outage (Xh Ym)"
    2. Rainfall >= RAIN_MM_THRESHOLD                  → "Heavy rain (X mm)"
    3. Event at nearest_station AND ridership UP       → "Event: <name>"
    4. Sibling routes in same corridor also down       → "Corridor-wide disruption"
    5. Breakdowns above normal on same route           → "Vehicle breakdowns (N)"
    6. None                                            → "No clear cause in available data"

Confidence: >= 2 agreeing signals = "Likely", 1 signal = "Possible", 0 = "Unknown".
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from app.config import RAIN_MM_THRESHOLD
from app.core.detect import Exception_


def attach_causes(
    exceptions: list[Exception_],
    dfs: dict[str, Optional[pd.DataFrame]],
    target_date: date,
) -> list[Exception_]:
    """Mutates each Exception_ in place: fills cause_label, confidence, evidence."""
    weather  = dfs.get("weather")
    events   = dfs.get("events")
    incidents= dfs.get("metro_incidents")
    brts     = dfs.get("brts_daily")
    amts     = dfs.get("amts_daily")

    # ── Pre-compute context for the target date ───────────────────────────────
    rain_mm   = _get_rain(weather, target_date)
    day_events= _get_events(events, target_date)           # list of event dicts
    incidents_today = _get_incidents(incidents, target_date)  # station → list[incident]

    for ex in exceptions:
        evidence: list[str] = []
        cause_parts: list[str] = []
        primary_cat: Optional[str] = None

        # 1. Incident at same station (Metro only)
        if ex.system == "METRO" and ex.entity_id in incidents_today:
            for inc in incidents_today[ex.entity_id]:
                hrs  = inc["duration_min"] // 60
                mins = inc["duration_min"] %  60
                inc_type = inc["type"].capitalize()
                label = (f"{inc_type} outage {hrs}h {mins}m" if hrs else
                         f"{inc_type} outage {mins}m")
                cause_parts.append(label)
                evidence.append(f"Incident log: {label} at {ex.entity_id}")
                if not primary_cat:
                    primary_cat = "gate_outage" if inc["type"].lower() == "gate" else "lift_or_escalator_fault"

        # 2. Heavy rain
        if rain_mm >= RAIN_MM_THRESHOLD:
            cause_parts.append(f"Heavy rain ({rain_mm:.0f} mm)")
            evidence.append(f"Weather: {rain_mm:.0f} mm rainfall")
            if not primary_cat:
                primary_cat = "heavy_rain"

        # 3. Event at nearest station AND ridership UP
        for ev in day_events:
            if ev["nearest_station"] == ex.entity_id and ex.direction == "up":
                cause_parts.append(f"Event: {ev['name']}")
                evidence.append(
                    f"Event '{ev['name']}' at {ev['venue']} "
                    f"({ev['expected_attendance']:,} expected attendance)")
                if not primary_cat:
                    primary_cat = "event_surge"

        # 4. Sibling-route corridor-wide disruption (BRTS / AMTS)
        if ex.system in ("BRTS", "AMTS") and ex.metric in ("trips_ratio", "ridership"):
            corridor_flag, siblings = _corridor_disruption(
                ex.entity_id, ex.system, brts, amts, target_date)
            if corridor_flag:
                cause_parts.append("Corridor-wide disruption")
                evidence.append(f"Sibling routes also low: {', '.join(siblings)}")
                if not primary_cat:
                    primary_cat = "corridor_wide_disruption"

        # 5. Breakdown spike on same route (skip if this exception IS a breakdown)
        if ex.metric != "breakdowns":
            bkd_count = _breakdowns_on_route(ex.entity_id, ex.system, brts, amts, target_date)
            if bkd_count >= 2:
                cause_parts.append(f"Vehicle breakdowns ({bkd_count})")
                evidence.append(f"{bkd_count} vehicle breakdown(s) recorded on {ex.entity_id}")
                if not primary_cat:
                    primary_cat = "vehicle_breakdowns"
                    
        # Explicitly handle metric=breakdowns for AMTS/BRTS
        if ex.metric == "breakdowns" and not primary_cat:
            primary_cat = "vehicle_breakdowns"

        # ── Confidence assignment ─────────────────────────────────────────────
        n_signals = len(cause_parts)
        if n_signals == 0:
            cause_label = "No clear cause in available data"
            confidence  = "Unknown"
            if not primary_cat:
                primary_cat = "unknown"
        elif n_signals == 1:
            cause_label = cause_parts[0]
            confidence  = "Possible"
        else:
            cause_label = " + ".join(cause_parts)
            confidence  = "Likely"

        ex.cause_label = cause_label
        ex.confidence  = confidence
        ex.evidence    = evidence
        ex.cause_category = primary_cat or "unknown"

    return exceptions


# ── Context helpers ───────────────────────────────────────────────────────────

def _get_rain(weather: Optional[pd.DataFrame], d: date) -> float:
    if weather is None:
        return 0.0
    row = weather[weather["date"] == d]
    if row.empty:
        return 0.0
    return float(row["rainfall_mm"].iloc[0])


def _get_events(events: Optional[pd.DataFrame], d: date) -> list[dict]:
    if events is None:
        return []
    rows = events[events["date"] == d]
    return rows.to_dict("records")


def _get_incidents(
    incidents: Optional[pd.DataFrame],
    d: date,
) -> dict[str, list[dict]]:
    """Returns mapping station → list of incident dicts for the given date."""
    result: dict[str, list[dict]] = {}
    if incidents is None:
        return result
    rows = incidents[incidents["date"] == d]
    for _, row in rows.iterrows():
        station = str(row["station"])
        result.setdefault(station, []).append({
            "type": str(row["type"]),
            "duration_min": int(row["duration_min"]),
        })
    return result


def _corridor_disruption(
    entity_id: str,
    system: str,
    brts: Optional[pd.DataFrame],
    amts: Optional[pd.DataFrame],
    d: date,
) -> tuple[bool, list[str]]:
    """Checks if sibling routes (same system) are also below trips_ratio threshold."""
    from app.config import TRIPS_RATIO
    df = brts if system == "BRTS" else amts
    if df is None:
        return False, []
    today = df[df["date"] == d].copy()
    if today.empty:
        return False, []
    today["trips_ratio"] = today["trips_run"] / today["trips_planned"].replace(0, pd.NA)
    # Siblings = all routes except the one being analysed
    siblings_low = today[
        (today["route"] != entity_id) &
        (today["trips_ratio"] < TRIPS_RATIO)
    ]["route"].tolist()
    return len(siblings_low) >= 1, siblings_low


def _breakdowns_on_route(
    entity_id: str,
    system: str,
    brts: Optional[pd.DataFrame],
    amts: Optional[pd.DataFrame],
    d: date,
) -> int:
    df = brts if system == "BRTS" else amts
    if df is None:
        return 0
    row = df[(df["date"] == d) & (df["route"] == entity_id)]
    if row.empty:
        return 0
    return int(row["breakdowns"].iloc[0])


if __name__ == "__main__":
    from datetime import date as dt
    from ingest import ingest
    from normalize import normalize
    from baseline import compute_baselines
    from detect import detect

    dfs, _    = ingest()
    long      = normalize(dfs, dt(2026, 10, 10))
    analysis, _= compute_baselines(long, dt(2026, 10, 10))
    top, _    = detect(analysis, dfs, dt(2026, 10, 10))
    top       = attach_causes(top, dfs, dt(2026, 10, 10))
    for ex in top:
        print(f"[{ex.severity}] {ex.entity_id} / {ex.metric}")
        print(f"  Cause: {ex.cause_label}  ({ex.confidence})")
        for ev in ex.evidence:
            print(f"    • {ev}")
