# SavarSignal

SavarSignal is a fast, offline-first morning brief generator for city public transport networks (Metro, BRTS, AMTS). It digests raw CSV data and instantly produces a prioritized, highly-readable executive summary of operational anomalies, complete with root causes and suggested actions.

## 🚀 Quick Start

### 1. Setup Environment
```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash
# venv\Scripts\activate        # Windows CMD

pip install fastapi uvicorn jinja2 pandas numpy requests python-multipart pytest
```

### 2. Build Tailwind CSS
```bash
npx @tailwindcss/cli@next -i ./static/input.css -o ./static/style.css
```

### 3. Run the Application
```bash
# Start the FastAPI server
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000` in your browser. 
Click **Load Demo Data** to generate synthetic data, then **Generate Brief** to view the report.

## 📁 Folder Structure
For proper organization, the codebase should be restructured as follows:

```text
SavarSignal/
├── app/
│   ├── main.py            # FastAPI entrypoint (formerly app.py)
│   ├── config.py          # Tuning thresholds
│   ├── datagen.py         # Demo data generator
│   └── core/
│       ├── ingest.py      # Data loading
│       ├── normalize.py   # Data formatting
│       ├── baseline.py    # Historical medians
│       ├── detect.py      # Anomaly detection
│       ├── causes.py      # Evidence mapping
│       ├── narrate.py     # Sentence building
│       ├── history.py     # Recurring offender tracking
│       └── render.py      # HTML generation
├── data/                  # Sample CSVs, history DB, generated briefs
├── static/                # Tailwind CSS
├── templates/             # HTML Templates
├── tests/                 # Pytest suite
├── .gitignore
└── README.md
```

## ✨ Core Features
- **Offline-First**: Generates briefs instantly without requiring cloud services.
- **Recurring Offender Tracker**: Remembers recurring issues over a 14-day window and automatically escalates their priority.
- **Smart Root Cause Mapping**: Uses contextual data (weather, events, breakdowns) to correctly map incidents to likely causes.
- **Optional LLM Polish**: If LM Studio is running locally on port `1234` (`nous-hermes-2-mistral-7b-dpo`), it automatically connects to polish the observation sentences natively.

## 🧪 Testing
```bash
pytest tests/ -v
```
