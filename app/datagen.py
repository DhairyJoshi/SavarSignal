"""
datagen.py – Generates realistic synthetic CSV data for the demo.

Produces 5 weeks of history plus the target day for:
  • 6 Metro stations
  • 5 BRTS routes
  • 6 AMTS routes

Injects 5 known anomalies (see demo_truth.json) so the pipeline can be validated.
"""

import json
import os
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.config import DATA_DIR, DEMO_TRUTH_JSON

random.seed(42)
np.random.seed(42)

# ── Constants ─────────────────────────────────────────────────────────────────
TARGET_DATE   = date(2026, 10, 10)   # The "today" the brief is about
HISTORY_WEEKS = 5
STATIONS = [
    "Thaltej Gam", "Thaltej", "Doordarshan Kendra", "Gurukul Road", 
    "Gujarat University", "Commerce Six Road", "SP Stadium", "Old High Court", 
    "Shahpur", "Gheekanta", "Kalupur Railway Station", "Kankaria East", 
    "Apparel Park", "Amraiwadi", "Rabari Colony", "Vastral", "Nirant Cross Road", 
    "Vastral Gam", "APMC", "Jivraj Park", "Rajivnagar", "Shreyas", "Paldi", 
    "Gandhigram", "Usmanpura", "Vijay Nagar", "Vadaj", "Ranip", 
    "Sabarmati Railway Station", "AEC", "Sabarmati", "Motera Stadium", 
    "Koteshwar Road", "Vishwakarma College", "Tapovan Circle", "Narmada Canal", 
    "Koba Circle", "Juna Koba", "Koba Gam", "GNLU", "Raysan", "Randesan", 
    "Dholakuva Circle", "Infocity", "Sector-1", "Sector-10A", "Sachivalaya", 
    "Akshardham", "Juna Sachivalaya", "Sector-16", "Sector-24", "Mahatma Mandir", 
    "PDEU", "GIFT City"
]
BRTS_ROUTES = [
    "Line 1 (RTO Circular)", "Line 2 (RTO Anti-Circular)", 
    "Line 3 (RTO to Maninagar)", "Line 4 (RTO to Hathijan)", 
    "Line 5 (Bopal to Maninagar)", "Line 6 (Soni Ni Chali to Odhav)", 
    "Line 7 (Zundal to Commerce Six)", "Line 8 (Visat to Naroda)"
]
AMTS_ROUTES = [
    "Route 31 (Lal Darwaja - Sarkhej)", "Route 34/4 (Lal Darwaja - Bopal)", 
    "Route 45 (Lal Darwaja - Odhav)", "Route 58 (Lal Darwaja - Naroda)", 
    "Route 61 (Lal Darwaja - Vasna)", "Route 136 (Lal Darwaja - Maninagar)"
]

# Base weekday ridership per station (entries)
BASE_ENTRIES = {s: random.randint(2500, 7000) for s in STATIONS}
BASE_ENTRIES["Paldi"] = 5200   # Paldi has a well-known baseline

# Weekday vs weekend multiplier
def day_mult(d: date) -> float:
    return 1.0 if d.weekday() < 5 else 0.55

# ── Metro daily ───────────────────────────────────────────────────────────────
def gen_metro_daily(dates: list[date], anomaly_date: date) -> pd.DataFrame:
    rows = []
    hour_bands = ["06-09", "09-12", "12-15", "15-18", "18-21", "21-24"]
    for d in dates:
        for station in STATIONS:
            base = BASE_ENTRIES[station] * day_mult(d)
            noise = np.random.normal(1.0, 0.04)
            total_entries = int(base * noise)
            total_exits   = int(total_entries * np.random.uniform(0.92, 0.98))
            gate_down = 0

            # Anomaly 1 – Paldi: gate outage + rain effect on anomaly_date
            if d == anomaly_date and station == "Paldi":
                total_entries = int(total_entries * 0.88)   # -12%
                gate_down = 380                              # 6+ hours downtime

            # Distribute across hour bands
            weights = [0.15, 0.20, 0.10, 0.15, 0.25, 0.15]
            for i, hb in enumerate(hour_bands):
                band_entries = int(total_entries * weights[i] + np.random.normal(0, 20))
                band_exits   = int(total_exits   * weights[i] + np.random.normal(0, 15))
                rows.append(dict(
                    date=d.isoformat(),
                    station=station,
                    hour_band=hb,
                    entries=max(0, band_entries),
                    exits=max(0, band_exits),
                    gate_downtime_min=gate_down if i == 0 else 0,
                ))
    return pd.DataFrame(rows)


# ── Metro incidents ───────────────────────────────────────────────────────────
def gen_metro_incidents(anomaly_date: date) -> pd.DataFrame:
    rows = [
        # Background incidents
        dict(date=(anomaly_date - timedelta(days=3)).isoformat(),
             station="Motera Stadium", type="escalator", duration_min=45),
        dict(date=(anomaly_date - timedelta(days=1)).isoformat(),
             station="Old High Court", type="lift", duration_min=90),
        # Anomaly 1 – gate outage at Paldi
        dict(date=anomaly_date.isoformat(), station="Paldi", type="gate", duration_min=380),
    ]
    return pd.DataFrame(rows)


# ── BRTS daily ────────────────────────────────────────────────────────────────
def gen_brts_daily(dates: list[date], anomaly_date: date) -> pd.DataFrame:
    rows = []
    for d in dates:
        for route in BRTS_ROUTES:
            planned = 42 if d.weekday() < 5 else 28
            noise   = np.random.normal(1.0, 0.03)
            run     = min(planned, int(planned * noise))
            boards  = int(run * np.random.randint(35, 55) * day_mult(d))
            breakd  = 0
            if np.random.random() < 0.05:
                breakd = 1

            # Anomaly 4 – Line 3 and Line 4 corridor-wide disruption
            if d == anomaly_date and route in ("Line 3 (RTO to Maninagar)", "Line 4 (RTO to Hathijan)"):
                run    = int(planned * 0.72)   # 72% service
                boards = int(boards * 0.75)
                breakd = 3

            rows.append(dict(
                date=d.isoformat(),
                route=route,
                trips_planned=planned,
                trips_run=run,
                boardings=max(0, boards),
                breakdowns=breakd,
            ))
    return pd.DataFrame(rows)


# ── AMTS daily ────────────────────────────────────────────────────────────────
def gen_amts_daily(dates: list[date], anomaly_date: date) -> pd.DataFrame:
    rows = []
    for d in dates:
        for route in AMTS_ROUTES:
            planned = 38 if d.weekday() < 5 else 22
            noise   = np.random.normal(1.0, 0.04)
            run     = min(planned, int(planned * noise))
            boards  = int(run * np.random.randint(28, 48) * day_mult(d))
            breakd  = 0
            if np.random.random() < 0.05:
                breakd = 1

            # Anomaly 3 – Route 58: 5 breakdowns, trips run 82%
            if d == anomaly_date and route == "Route 58 (Lal Darwaja - Naroda)":
                run    = int(planned * 0.82)
                breakd = 5
                boards = int(boards * 0.80)

            # Anomaly 5 – Route 34/4: unexplained ridership drop (no matching context)
            if d == anomaly_date and route == "Route 34/4 (Lal Darwaja - Bopal)":
                boards = int(boards * 0.72)
                run    = int(planned * 0.88)

            rows.append(dict(
                date=d.isoformat(),
                route=route,
                trips_planned=planned,
                trips_run=run,
                boardings=max(0, boards),
                breakdowns=breakd,
            ))
    return pd.DataFrame(rows)


# ── Weather ───────────────────────────────────────────────────────────────────
def gen_weather(dates: list[date], anomaly_date: date) -> pd.DataFrame:
    rows = []
    for d in dates:
        rain  = max(0, np.random.normal(3, 4))
        temp  = np.random.normal(31, 3)
        # Anomaly 1 – heavy rain on anomaly_date
        if d == anomaly_date:
            rain = 38.0
        rows.append(dict(date=d.isoformat(), rainfall_mm=round(rain, 1),
                         max_temp_c=round(temp, 1)))
    return pd.DataFrame(rows)


# ── Events ────────────────────────────────────────────────────────────────────
def gen_events(anomaly_date: date) -> pd.DataFrame:
    rows = [
        # Background events
        dict(date=(anomaly_date - timedelta(days=2)).isoformat(),
             name="Navratri Garba Night",
             venue="GMDC Grounds",
             nearest_station="Gujarat University",
             expected_attendance=25000),
        # Anomaly 2 – cricket event → ridership UP at Motera Stadium (nearest)
        dict(date=anomaly_date.isoformat(),
             name="T20 Cricket Match",
             venue="Narendra Modi Stadium",
             nearest_station="Motera Stadium",
             expected_attendance=50000),
    ]
    return pd.DataFrame(rows)


# ── Station Y (Anomaly 2 – ridership spike) ───────────────────────────────────
# We inject the cricket event spike directly into metro_daily for "Motera Stadium"
def inject_anomaly2(df_metro: pd.DataFrame, anomaly_date: date) -> pd.DataFrame:
    """Boost Motera Stadium ridership +35% on anomaly_date."""
    mask = (df_metro["date"] == anomaly_date.isoformat()) & \
           (df_metro["station"] == "Motera Stadium")
    df_metro.loc[mask, "entries"] = (df_metro.loc[mask, "entries"] * 1.35).astype(int)
    df_metro.loc[mask, "exits"]   = (df_metro.loc[mask, "exits"]   * 1.35).astype(int)
    return df_metro


# ── Main ──────────────────────────────────────────────────────────────────────
def generate(target_date: date = TARGET_DATE, out_dir: str = DATA_DIR):
    os.makedirs(out_dir, exist_ok=True)

    # Build date list: HISTORY_WEEKS * 7 days + target day
    start_date = target_date - timedelta(weeks=HISTORY_WEEKS)
    all_dates  = [start_date + timedelta(days=i)
                  for i in range((target_date - start_date).days + 1)]

    metro_daily     = gen_metro_daily(all_dates, target_date)
    metro_daily     = inject_anomaly2(metro_daily, target_date)
    metro_incidents = gen_metro_incidents(target_date)
    brts_daily      = gen_brts_daily(all_dates, target_date)
    amts_daily      = gen_amts_daily(all_dates, target_date)
    weather         = gen_weather(all_dates, target_date)
    events          = gen_events(target_date)

    metro_daily.to_csv(    os.path.join(out_dir, "metro_daily.csv"),     index=False)
    metro_incidents.to_csv(os.path.join(out_dir, "metro_incidents.csv"), index=False)
    brts_daily.to_csv(     os.path.join(out_dir, "brts_daily.csv"),      index=False)
    amts_daily.to_csv(     os.path.join(out_dir, "amts_daily.csv"),      index=False)
    weather.to_csv(        os.path.join(out_dir, "weather.csv"),         index=False)
    events.to_csv(         os.path.join(out_dir, "events.csv"),          index=False)

    # Ground truth for testing
    truth = {
        "target_date": target_date.isoformat(),
        "anomalies": [
            {
                "id": 1,
                "entity": "Paldi",
                "system": "METRO",
                "metric": "ridership",
                "direction": "down",
                "expected_pct": -12,
                "expected_cause": "gate_outage",
                "expected_confidence": "Likely",
            },
            {
                "id": 2,
                "entity": "Motera Stadium",
                "system": "METRO",
                "metric": "ridership",
                "direction": "up",
                "expected_pct": 35,
                "expected_cause": "event",
                "expected_confidence": "Likely",
            },
            {
                "id": 3,
                "entity": "Route 58 (Lal Darwaja - Naroda)",
                "system": "AMTS",
                "metric": "breakdowns",
                "direction": "up",
                "expected_cause": "vehicle_breakdowns",
                "expected_confidence": "Likely",
            },
            {
                "id": 4,
                "entity": "Line 3 (RTO to Maninagar)",
                "system": "BRTS",
                "metric": "trips_ratio",
                "direction": "down",
                "expected_cause": "corridor_disruption",
                "expected_confidence": "Possible",
            },
            {
                "id": 5,
                "entity": "Route 34/4 (Lal Darwaja - Bopal)",
                "system": "AMTS",
                "metric": "ridership",
                "direction": "down",
                "expected_cause": "unknown",
                "expected_confidence": "Unknown",
            },
        ],
    }
    with open(DEMO_TRUTH_JSON, "w") as f:
        json.dump(truth, f, indent=2)

    print(f"[datagen] Generated data in {out_dir}")
    print(f"  Metro daily rows   : {len(metro_daily)}")
    print(f"  BRTS daily rows    : {len(brts_daily)}")
    print(f"  AMTS daily rows    : {len(amts_daily)}")
    print(f"  Weather rows       : {len(weather)}")
    print(f"  Events             : {len(events)}")
    print(f"  Incidents          : {len(metro_incidents)}")
    print(f"  demo_truth.json    : {DEMO_TRUTH_JSON}")
    return out_dir


if __name__ == "__main__":
    generate()
