"""
tests/test_detect.py – Unit tests for anomaly detection rules.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
import numpy as np
from datetime import date

from app.core.detect import detect, Exception_

TARGET = date(2026, 10, 10)


def _make_analysis(entity_id, system, metric, value, baseline, spread=None, entity_type="station"):
    """Build a minimal one-row analysis DataFrame."""
    if spread is None:
        spread = baseline * 0.05
    pct = (value - baseline) / baseline if baseline else 0
    z   = (value - baseline) / spread if spread > 0 else 0
    return pd.DataFrame([{
        "date": TARGET,
        "system": system,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metric": metric,
        "value": value,
        "baseline": baseline,
        "spread": spread,
        "n_history": 4,
        "pct_change": pct,
        "z": z,
    }])


class TestRidershipRule:
    def test_large_drop_flagged(self):
        df = _make_analysis("Station X", "METRO", "ridership",
                            value=4576, baseline=5200, spread=100)
        top, overflow = detect(df, {}, TARGET, top_n=6)
        assert any(e.entity_id == "Station X" and e.metric == "ridership" for e in top)

    def test_small_drop_not_flagged(self):
        """3% drop should NOT be flagged (below 10% threshold)."""
        df = _make_analysis("Station A", "METRO", "ridership",
                            value=5044, baseline=5200, spread=100)
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert not any(e.entity_id == "Station A" and e.metric == "ridership" for e in top)

    def test_dual_threshold_required(self):
        """Large pct change but tiny z-score (big spread) should NOT flag."""
        df = _make_analysis("Station B", "METRO", "ridership",
                            value=3000, baseline=5200, spread=3000)  # z≈0.73
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert not any(e.entity_id == "Station B" and e.metric == "ridership" for e in top)

    def test_ridership_spike_up_flagged(self):
        df = _make_analysis("Station B", "METRO", "ridership",
                            value=7020, baseline=5200, spread=100)
        top, _ = detect(df, {}, TARGET, top_n=6)
        flagged = [e for e in top if e.entity_id == "Station B" and e.metric == "ridership"]
        assert flagged
        assert flagged[0].direction == "up"

    def test_severity_high_for_large_deviation(self):
        df = _make_analysis("Station X", "METRO", "ridership",
                            value=2000, baseline=5200, spread=100)
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert top[0].severity == "High"


class TestTripsRatioRule:
    def test_low_service_flagged(self):
        df = _make_analysis("BRTS-13", "BRTS", "trips_ratio",
                            value=0.72, baseline=0.98, spread=0.02, entity_type="route")
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert any(e.entity_id == "BRTS-13" and e.metric == "trips_ratio" for e in top)

    def test_90pct_not_flagged(self):
        df = _make_analysis("BRTS-11", "BRTS", "trips_ratio",
                            value=0.91, baseline=0.98, spread=0.02, entity_type="route")
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert not any(e.entity_id == "BRTS-11" and e.metric == "trips_ratio" for e in top)


class TestBreakdownRule:
    def test_spike_flagged(self):
        df = _make_analysis("AMTS-4", "AMTS", "breakdowns",
                            value=5.0, baseline=1.0, spread=0.3, entity_type="route")
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert any(e.entity_id == "AMTS-4" and e.metric == "breakdowns" for e in top)

    def test_single_breakdown_not_flagged(self):
        """1 breakdown with baseline 0.5 → 2x rule not met (2 * 0.5 = 1, but needs ≥ 2 abs)."""
        df = _make_analysis("AMTS-1", "AMTS", "breakdowns",
                            value=1.0, baseline=0.5, spread=0.2, entity_type="route")
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert not any(e.entity_id == "AMTS-1" and e.metric == "breakdowns" for e in top)


class TestGateDowntimeRule:
    def test_long_downtime_flagged(self):
        df = _make_analysis("Station X", "METRO", "gate_downtime_min",
                            value=380.0, baseline=10.0, spread=5.0)
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert any(e.entity_id == "Station X" and e.metric == "gate_downtime_min" for e in top)

    def test_short_downtime_not_flagged(self):
        df = _make_analysis("Station A", "METRO", "gate_downtime_min",
                            value=45.0, baseline=10.0, spread=5.0)
        top, _ = detect(df, {}, TARGET, top_n=6)
        assert not any(e.entity_id == "Station A" and e.metric == "gate_downtime_min" for e in top)


class TestTopN:
    def test_top_n_cap(self):
        rows = []
        for i in range(10):
            rows.append({
                "date": TARGET, "system": "METRO", "entity_type": "station",
                "entity_id": f"Station {i}", "metric": "ridership",
                "value": 1000.0, "baseline": 5000.0, "spread": 50.0,
                "n_history": 4,
                "pct_change": -0.8, "z": -80.0,
            })
        df = pd.DataFrame(rows)
        top, overflow = detect(df, {}, TARGET, top_n=6)
        assert len(top) == 6
        assert len(overflow) == 4
