"""
narrate.py – Builds the plain-language sentence for each exception.

Two-pass approach:
    1. Template pass (always): deterministic sentence from structured fields.
    2. LLM pass (optional): sends facts to LM Studio; validates output;
       falls back to template if LLM is slow, unavailable, or output is invalid.

Also builds the 2-line executive summary.
"""

from __future__ import annotations

import re
import threading
from datetime import date
from typing import Callable, Optional

import requests

from app.config import (LLM_URL, LLM_MODEL, LLM_TIMEOUT,
                    LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_MAX_WORDS)
from app.core.detect import Exception_

# Day-of-week names
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]


# ── Template builder ──────────────────────────────────────────────────────────

def _template_sentence(ex: Exception_, target_date: date) -> str:
    weekday = WEEKDAY_NAMES[target_date.weekday()]
    direction = "up" if ex.direction == "up" else "down"

    if ex.metric == "ridership":
        pct_str = f"{abs(ex.pct_change) * 100:.0f}%"
        base = (f"{ex.entity_id} ridership {direction} {pct_str} vs usual {weekday}")
    elif ex.metric == "trips_ratio":
        pct_run = ex.value * 100
        base = (f"{ex.entity_id} service at {pct_run:.0f}% of planned trips")
    elif ex.metric == "breakdowns":
        base = (f"{ex.entity_id}: {int(ex.value)} vehicle breakdown(s) "
                f"(normal ≈ {ex.baseline:.1f})")
    elif ex.metric == "gate_downtime_min":
        hrs  = int(ex.value) // 60
        mins = int(ex.value) % 60
        base = (f"{ex.entity_id}: gate downtime {hrs}h {mins}m")
    else:
        base = f"{ex.entity_id} / {ex.metric}: {ex.value:.1f} (baseline {ex.baseline:.1f})"

    if ex.cause_label and ex.cause_label != "No clear cause in available data":
        sentence = f"{base}; likely cause: {ex.cause_label}."
    elif ex.cause_label == "No clear cause in available data":
        sentence = f"{base}; cause unclear from available data."
    else:
        sentence = f"{base}."

    return sentence


def build_template_narratives(
    exceptions: list[Exception_],
    target_date: date,
) -> list[Exception_]:
    """Fills narrative + narrative_source for every exception using templates."""
    for ex in exceptions:
        ex.narrative = _template_sentence(ex, target_date)
        ex.narrative_source = "template"
    return exceptions


# ── LLM helpers ──────────────────────────────────────────────────────────────

def _llm_rewrite(ex: Exception_, target_date: date) -> Optional[str]:
    """
    Calls LM Studio and returns the polished sentence, or None on failure.
    Validates: <= LLM_MAX_WORDS words, all numbers in output exist in input facts.
    """
    weekday = WEEKDAY_NAMES[target_date.weekday()]

    # Build the facts block
    pct_str    = f"{ex.pct_change * 100:+.0f}%"
    facts_parts = [
        f"{ex.entity_id} ({ex.system}) {ex.metric} {pct_str} vs usual {weekday}.",
    ]
    if ex.evidence:
        facts_parts.append("Evidence: " + "; ".join(ex.evidence) + ".")
    facts = " ".join(facts_parts)

    messages = [
        {
            "role": "system",
            "content": (
                "You write one-sentence transport MIS notes. "
                "Use only the facts given. Max 25 words. No introductory phrases."
            ),
        },
        {
            "role": "user",
            "content": f"Facts: {facts}\nWrite the note.",
        },
    ]

    try:
        resp = requests.post(
            LLM_URL,
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": LLM_TEMPERATURE,
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None

    # Validate word count
    if len(text.split()) > LLM_MAX_WORDS:
        return None

    # Validate: every number in LLM output must exist in facts
    llm_numbers  = set(re.findall(r"\d+\.?\d*", text))
    fact_numbers = set(re.findall(r"\d+\.?\d*", facts))
    if not llm_numbers.issubset(fact_numbers):
        return None

    return text


def polish_with_llm(
    exceptions: list[Exception_],
    target_date: date,
    on_update: Optional[Callable[[Exception_], None]] = None,
) -> list[Exception_]:
    """
    Rewrites narratives using LLM (blocking, call in a background thread).
    Calls on_update(ex) after each successful rewrite.
    """
    for ex in exceptions:
        polished = _llm_rewrite(ex, target_date)
        if polished:
            ex.narrative = polished
            ex.narrative_source = "llm"
        if on_update:
            on_update(ex)
    return exceptions


def build_executive_summary(
    exceptions: list[Exception_],
    target_date: date,
    dfs: dict,
    llm_available: bool = False,
) -> str:
    """Build a 2-line executive summary from the top exceptions."""
    if not exceptions:
        return "No significant exceptions detected for " + target_date.isoformat() + "."

    high   = [e for e in exceptions if e.severity == "High"]
    medium = [e for e in exceptions if e.severity == "Medium"]
    n_all  = len(exceptions)

    systems_affected = list(dict.fromkeys(e.system for e in exceptions))

    line1 = (
        f"{n_all} exception(s) detected across "
        f"{', '.join(systems_affected)} on "
        f"{target_date.strftime('%d %b %Y')} ({WEEKDAY_NAMES[target_date.weekday()]})."
    )

    if high:
        top = high[0]
        line2 = (
            f"Highest priority: {top.entity_id} ({top.system}) — "
            f"{top.narrative}"
        )
    elif medium:
        top = medium[0]
        line2 = f"Notable: {top.entity_id} — {top.narrative}"
    else:
        line2 = "All exceptions are low severity."

    recurring_count = sum(1 for e in exceptions if getattr(e, 'recurrence_count', 1) >= 2)
    if recurring_count > 0:
        line3 = f"{recurring_count} issue(s) are recurring and have been escalated."
        return f"{line1}\n{line2}\n{line3}"

    return f"{line1}\n{line2}"


# ── LLM availability check ────────────────────────────────────────────────────

def check_llm_health() -> bool:
    """Returns True if LM Studio is reachable."""
    try:
        resp = requests.get(
            "http://localhost:1234/v1/models",
            timeout=3,
        )
        return resp.status_code == 200
    except Exception:
        return False
