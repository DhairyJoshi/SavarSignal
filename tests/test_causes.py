"""
tests/test_causes.py – Unit tests for the cause engine.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
from datetime import date

from app.core.detect import Exception_
from app.core.causes import attach_causes

TARGET = date(2026, 10, 10)


def _make_ex(entity_id, system, metric="ridership", direction="down",
             value=4576.0, baseline=5200.0, pct=-0.12, rule="ridership"):
    return Exception_(
        entity_id=entity_id, system=system, entity_type="station",
        metric=metric, value=value, baseline=baseline,
        pct_change=pct, z=-2.5, rule=rule,
        severity="High", severity_score=70.0, direction=direction,
    )


class TestCauseEngine:

    def test_gate_incident_causes_cause(self):
        """A gate incident at the same station should produce a gate-outage cause."""
        inc_df = pd.DataFrame([{
            "date": TARGET, "station": "Station X",
            "type": "gate", "duration_min": 380,
        }])
        dfs = {"metro_incidents": inc_df, "weather": None, "events": None,
               "brts_daily": None, "amts_daily": None}
        ex = _make_ex("Station X", "METRO")
        result = attach_causes([ex], dfs, TARGET)
        assert "gate" in result[0].cause_label.lower() or "outage" in result[0].cause_label.lower()
        assert result[0].confidence in ("Possible", "Likely")

    def test_heavy_rain_adds_evidence(self):
        """Rainfall >= 25mm should appear in evidence and cause."""
        weather_df = pd.DataFrame([{
            "date": TARGET, "rainfall_mm": 38.0, "max_temp_c": 29.0,
        }])
        dfs = {"metro_incidents": None, "weather": weather_df,
               "events": None, "brts_daily": None, "amts_daily": None}
        ex = _make_ex("Station A", "METRO")
        result = attach_causes([ex], dfs, TARGET)
        assert any("rain" in e.lower() or "38" in e for e in result[0].evidence)

    def test_event_with_ridership_up(self):
        """An event at nearest_station should be detected when ridership is UP."""
        events_df = pd.DataFrame([{
            "date": TARGET, "name": "T20 Cricket Match",
            "venue": "Stadium", "nearest_station": "Station B",
            "expected_attendance": 50000,
        }])
        dfs = {"metro_incidents": None, "weather": None,
               "events": events_df, "brts_daily": None, "amts_daily": None}
        ex = _make_ex("Station B", "METRO", direction="up", pct=0.35, value=7020, baseline=5200)
        result = attach_causes([ex], dfs, TARGET)
        assert any("cricket" in e.lower() or "t20" in e.lower()
                   for e in result[0].evidence)
        assert "Event" in result[0].cause_label

    def test_event_not_applied_when_ridership_down(self):
        """An event near a station where ridership is DOWN should NOT appear as cause."""
        events_df = pd.DataFrame([{
            "date": TARGET, "name": "T20 Cricket Match",
            "venue": "Stadium", "nearest_station": "Station B",
            "expected_attendance": 50000,
        }])
        dfs = {"metro_incidents": None, "weather": None,
               "events": events_df, "brts_daily": None, "amts_daily": None}
        ex = _make_ex("Station B", "METRO", direction="down")
        result = attach_causes([ex], dfs, TARGET)
        assert "Event" not in result[0].cause_label

    def test_no_evidence_gives_unknown(self):
        """No matching evidence should produce Unknown confidence."""
        dfs = {"metro_incidents": None, "weather": None,
               "events": None, "brts_daily": None, "amts_daily": None}
        ex = _make_ex("Route 34/4 (Lal Darwaja - Bopal)", "AMTS")
        result = attach_causes([ex], dfs, TARGET)
        assert result[0].confidence == "Unknown"
        assert "No clear cause" in result[0].cause_label

    def test_two_signals_give_likely(self):
        """Gate incident + heavy rain should give Likely confidence."""
        inc_df = pd.DataFrame([{
            "date": TARGET, "station": "Station X",
            "type": "gate", "duration_min": 380,
        }])
        weather_df = pd.DataFrame([{
            "date": TARGET, "rainfall_mm": 38.0, "max_temp_c": 29.0,
        }])
        dfs = {"metro_incidents": inc_df, "weather": weather_df,
               "events": None, "brts_daily": None, "amts_daily": None}
        ex = _make_ex("Station X", "METRO")
        result = attach_causes([ex], dfs, TARGET)
        assert result[0].confidence == "Likely"

    def test_corridor_disruption(self):
        """Multiple sibling BRTS routes with low trips_ratio should trigger corridor-wide cause."""
        brts_df = pd.DataFrame([
            {"date": TARGET, "route": "Line 3 (RTO to Maninagar)", "trips_planned": 42, "trips_run": 30,
             "boardings": 800, "breakdowns": 2},
            {"date": TARGET, "route": "Line 4 (RTO to Hathijan)", "trips_planned": 42, "trips_run": 28,
             "boardings": 700, "breakdowns": 3},
            {"date": TARGET, "route": "Line 1 (RTO Circular)", "trips_planned": 42, "trips_run": 41,
             "boardings": 1200, "breakdowns": 0},
        ])
        dfs = {"metro_incidents": None, "weather": None, "events": None,
               "brts_daily": brts_df, "amts_daily": None}
        ex = _make_ex("Line 3 (RTO to Maninagar)", "BRTS", metric="trips_ratio", rule="trips_ratio")
        result = attach_causes([ex], dfs, TARGET)
        assert "corridor" in result[0].cause_label.lower() or \
               any("sibling" in e.lower() for e in result[0].evidence)


class TestEndToEnd:
    """Runs the full pipeline on generated demo data and checks all 5 injected anomalies."""

    def test_all_injected_anomalies_detected(self):
        import json
        from ingest import ingest
        from normalize import normalize
        from baseline import compute_baselines
        from detect import detect
        from causes import attach_causes
        from datagen import generate
        from config import DATA_DIR

        # Generate demo data fresh
        generate(target_date=date(2026, 10, 10), out_dir=DATA_DIR)

        dfs, _     = ingest(DATA_DIR)
        long       = normalize(dfs, TARGET)
        analysis, _= compute_baselines(long, TARGET)
        top, over  = detect(analysis, dfs, TARGET)
        top        = attach_causes(top, dfs, TARGET)
        all_ex     = top + over

        truth_path = os.path.join(DATA_DIR, "demo_truth.json")
        with open(truth_path) as f:
            truth = json.load(f)

        detected_ids = {(e.entity_id, e.system) for e in all_ex}

        for anomaly in truth["anomalies"]:
            entity = anomaly["entity"]
            system = anomaly["system"]
            assert (entity, system) in detected_ids, \
                f"Expected anomaly {anomaly['id']} ({entity}/{system}) not detected. Found: {detected_ids}"
