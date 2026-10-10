import json
import os
from datetime import date

from app.core.detect import Exception_

HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "history.json")

OWNER_ACTION_MAP = {
    "gate_outage": ("Metro Maintenance", "Schedule preventive inspection of the gate bank"),
    "lift_or_escalator_fault": ("Metro Maintenance", "Inspect the unit and check spare-parts stock"),
    "heavy_rain": ("Civic Drainage Cell", "Pre-position pumps; review entrance drainage before the next forecast"),
    "event_surge": ("Metro Operations", "Prepare a crowd plan and extra trains for the next event at this venue"),
    "vehicle_breakdowns": ("Depot Manager", "Run a fitness check on this route's fleet"),
    "corridor_wide_disruption": ("Corridor Control", "Review diversions and signal timing"),
    "unknown": ("MIS Analyst", "Investigate: no cause found in the available data")
}

def clear_history():
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_history(data):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def track_recurrences(exceptions: list[Exception_], target_date: date, window_days: int = 14) -> list[Exception_]:
    history = load_history()
    target_str = target_date.isoformat()
    
    # 1. Ask history for earlier matching days
    for ex in exceptions:
        owner, action = OWNER_ACTION_MAP.get(ex.cause_category, ("Control Room", "Review manually"))
        ex.owner = owner
        ex.action = action
        
        past_dates = []
        for dt_str, records in history.items():
            if dt_str >= target_str:
                continue # Only past dates
            
            # Check if within window
            dt = date.fromisoformat(dt_str)
            if (target_date - dt).days > window_days:
                continue
                
            for rec in records:
                if rec["entity_id"] == ex.entity_id and rec["cause_category"] == ex.cause_category:
                    past_dates.append(dt_str)
                    break
        
        past_dates.sort()
        ex.past_dates = past_dates
        ex.recurrence_count = len(past_dates) + 1
        
        if ex.recurrence_count >= 2:
            # Mark as recurring
            suffix = "th"
            if ex.recurrence_count % 10 == 1 and ex.recurrence_count % 100 != 11:
                suffix = "st"
            elif ex.recurrence_count % 10 == 2 and ex.recurrence_count % 100 != 12:
                suffix = "nd"
            elif ex.recurrence_count % 10 == 3 and ex.recurrence_count % 100 != 13:
                suffix = "rd"
                
            ex.recurrence_label = f"{ex.recurrence_count}{suffix} time in {window_days} days"
            ex.original_severity = ex.severity
            
            # Escalate severity
            if ex.severity == "Low":
                ex.severity = "Medium"
            elif ex.severity == "Medium":
                ex.severity = "High"
    
    # Save today's exceptions to history, replacing anything already stored for today
    today_records = []
    for ex in exceptions:
        today_records.append({
            "entity_id": ex.entity_id,
            "cause_category": ex.cause_category,
            "rule": ex.rule,
            "severity": ex.severity
        })
    
    history[target_str] = today_records
    save_history(history)
    
    # Re-sort by severity first, then existing score
    severity_order = {"High": 3, "Medium": 2, "Low": 1}
    exceptions.sort(key=lambda x: (severity_order.get(x.severity, 0), x.severity_score), reverse=True)
    
    return exceptions
