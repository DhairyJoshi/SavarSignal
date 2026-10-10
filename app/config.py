"""
config.py – Central configuration for the Two-Minute Morning Brief.
All thresholds are configurable here so judges can see how they would be tuned on real data.
"""

# ── Anomaly detection thresholds ──────────────────────────────────────────────
PCT_THRESHOLD = 0.10        # Flag if |pct_change| >= 10%
Z_THRESHOLD   = 2.0         # Flag if |z-score| >= 2.0  (dual threshold: both must fire)
TRIPS_RATIO   = 0.90        # Flag if trips_run / trips_planned < 90%
BREAKDOWN_MUL = 2.0         # Flag if breakdowns >= 2x baseline AND >= 2
GATE_MIN      = 120         # Flag if gate_downtime_min >= 120 minutes
TOP_N         = 5           # Maximum exceptions shown on the main brief page
MIN_HISTORY   = 3           # Minimum same-weekday history points needed

# ── Cause engine thresholds ───────────────────────────────────────────────────
RAIN_MM_THRESHOLD  = 25.0   # Heavy rain threshold in mm

# ── LLM settings (LM Studio, OpenAI-compatible) ──────────────────────────────
LLM_URL     = "http://localhost:1234/v1/chat/completions"
LLM_MODEL   = "nous-hermes-2-mistral-7b-dpo"   # Exact model ID in LM Studio
LLM_TIMEOUT = 8             # Seconds per call
LLM_MAX_TOKENS = 40
LLM_TEMPERATURE = 0.2
LLM_MAX_WORDS   = 25        # Discard LLM output if over this many words

# ── Data paths ────────────────────────────────────────────────────────────────
import os
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.path.join(BASE_DIR, "data", "sample")
BRIEFS_DIR = os.path.join(BASE_DIR, "data", "briefs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BRIEFS_DIR, exist_ok=True)

# CSV filenames (relative to DATA_DIR)
METRO_DAILY_CSV     = "metro_daily.csv"
METRO_INCIDENTS_CSV = "metro_incidents.csv"
BRTS_DAILY_CSV      = "brts_daily.csv"
AMTS_DAILY_CSV      = "amts_daily.csv"
WEATHER_CSV         = "weather.csv"
EVENTS_CSV          = "events.csv"
DEMO_TRUTH_JSON     = os.path.join(DATA_DIR, "demo_truth.json")
