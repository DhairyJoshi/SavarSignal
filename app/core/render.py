"""
render.py – Assembles the brief data model and renders it via Jinja2.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from app.config import BRIEFS_DIR
from app.core.detect import Exception_
from app.core.ingest import DataQualityReport


def _kpi_strip(
    dfs: dict,
    target_date: date,
) -> dict:
    """Compute headline KPIs for the three systems."""
    kpis = {}

    # Metro
    md = dfs.get("metro_daily")
    if md is not None:
        today = md[md["date"] == target_date]
        kpis["metro"] = {
            "total_ridership": int(today["entries"].sum()),
            "total_gate_downtime": int(today["gate_downtime_min"].sum()),
        }
    else:
        kpis["metro"] = None

    # BRTS
    bd = dfs.get("brts_daily")
    if bd is not None:
        today = bd[bd["date"] == target_date]
        planned = today["trips_planned"].sum()
        run     = today["trips_run"].sum()
        kpis["brts"] = {
            "trips_planned": int(planned),
            "trips_run":     int(run),
            "service_pct":   round(run / planned * 100, 1) if planned else 0,
            "total_boardings": int(today["boardings"].sum()),
            "breakdowns":    int(today["breakdowns"].sum()),
        }
    else:
        kpis["brts"] = None

    # AMTS
    ad = dfs.get("amts_daily")
    if ad is not None:
        today = ad[ad["date"] == target_date]
        planned = today["trips_planned"].sum()
        run     = today["trips_run"].sum()
        kpis["amts"] = {
            "trips_planned": int(planned),
            "trips_run":     int(run),
            "service_pct":   round(run / planned * 100, 1) if planned else 0,
            "total_boardings": int(today["boardings"].sum()),
            "breakdowns":    int(today["breakdowns"].sum()),
        }
    else:
        kpis["amts"] = None

    return kpis


def render_brief(
    target_date: date,
    dfs: dict,
    exceptions: list[Exception_],
    overflow_count: int,
    executive_summary: str,
    quality_report: DataQualityReport,
    llm_online: bool = False,
    brief_id: Optional[str] = None,
) -> tuple[str, str]:
    """
    Renders the brief HTML using Jinja2.

    Returns
    -------
    (brief_id, html_content)
    """
    if brief_id is None:
        brief_id = str(uuid.uuid4())[:8]

    kpis = _kpi_strip(dfs, target_date)

    # Template setup
    template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

    # Custom filter: format percentage
    def pct_fmt(v):
        if v is None:
            return "N/A"
        return f"{v * 100:+.1f}%"

    def abs_pct_fmt(v):
        if v is None:
            return "N/A"
        return f"{abs(v) * 100:.1f}%"

    env.filters["pct_fmt"] = pct_fmt
    env.filters["abs_pct_fmt"] = abs_pct_fmt

    tmpl = env.get_template("brief.html")
    html = tmpl.render(
        date=target_date,
        date_str=target_date.strftime("%d %B %Y"),
        weekday=target_date.strftime("%A"),
        kpis=kpis,
        exceptions=exceptions,
        overflow_count=overflow_count,
        executive_summary=executive_summary,
        quality_report=quality_report,
        llm_online=llm_online,
        brief_id=brief_id,
        missing_sources=[f for f in quality_report.missing_files],
    )

    # Save to disk
    out_path = os.path.join(BRIEFS_DIR, f"brief_{brief_id}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return brief_id, html
