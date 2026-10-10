"""
app.py – FastAPI web application for the Two-Minute Morning Brief.

Routes:
    GET  /                      → upload form
    POST /generate              → run the full pipeline, return brief_id
    GET  /brief/{id}            → rendered brief HTML
    GET  /brief/{id}/download   → standalone HTML download
    POST /demo                  → generate demo data + run pipeline
    GET  /health                → LLM reachability check
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import app.config as config
from app.core.baseline import compute_baselines
from app.core.causes import attach_causes
from app.datagen import generate as gen_demo_data
from app.core.detect import detect
from app.core.ingest import ingest, DataQualityReport
from app.core.narrate import (build_executive_summary, build_template_narratives,
                     check_llm_health, polish_with_llm)
from app.core.normalize import normalize
from app.core.render import render_brief

app = FastAPI(title="Two-Minute Morning Brief", version="1.0.0")

# Static files (compiled Tailwind CSS)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))

# In-memory brief store: brief_id → html_string
_briefs: dict[str, str] = {}
_brief_lock = threading.Lock()


# ── Helper: run the full pipeline ────────────────────────────────────────────

def _run_pipeline(
    target_date: date,
    data_dir: str,
    brief_id: Optional[str] = None,
) -> dict:
    """Run ingest → normalize → baseline → detect → causes → narrate → render."""
    dfs, quality_report = ingest(data_dir)
    long_df = normalize(dfs, target_date)
    analysis_df, skipped = compute_baselines(long_df, target_date)
    from app.config import TOP_N
    from app.core.history import track_recurrences

    all_exceptions, _ = detect(analysis_df, dfs, target_date, top_n=9999)
    all_exceptions = attach_causes(all_exceptions, dfs, target_date)
    all_exceptions = track_recurrences(all_exceptions, target_date)
    
    top_exceptions = all_exceptions[:TOP_N]
    overflow = all_exceptions[TOP_N:]
    
    top_exceptions = build_template_narratives(top_exceptions, target_date)
    llm_online = check_llm_health()
    executive_summary = build_executive_summary(top_exceptions, target_date, dfs, llm_online)

    bid, html = render_brief(
        target_date=target_date,
        dfs=dfs,
        exceptions=top_exceptions,
        overflow_count=len(overflow),
        executive_summary=executive_summary,
        quality_report=quality_report,
        llm_online=llm_online,
        brief_id=brief_id,
    )

    with _brief_lock:
        _briefs[bid] = html

    # Kick off background LLM polish
    if llm_online and top_exceptions:
        def _polish_bg():
            def _update(ex):
                # Re-render the brief after each LLM update
                _, updated_html = render_brief(
                    target_date=target_date,
                    dfs=dfs,
                    exceptions=top_exceptions,
                    overflow_count=len(overflow),
                    executive_summary=executive_summary,
                    quality_report=quality_report,
                    llm_online=True,
                    brief_id=bid,
                )
                with _brief_lock:
                    _briefs[bid] = updated_html

            polish_with_llm(top_exceptions, target_date, on_update=_update)

        t = threading.Thread(target=_polish_bg, daemon=True)
        t.start()

    return {
        "brief_id": bid,
        "exceptions_count": len(top_exceptions),
        "overflow_count": len(overflow),
        "llm_online": llm_online,
        "quality_issues": quality_report.has_issues,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    today = date.today().isoformat()
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "today": today})


@app.get("/health")
async def health():
    return JSONResponse({"llm_online": check_llm_health(), "status": "ok"})


@app.post("/demo")
async def demo():
    """Generate synthetic demo data and return the demo date."""
    try:
        from app.core.history import clear_history, save_history
        from datetime import date, timedelta
        
        clear_history()
        
        target = date(2026, 10, 10)
        seed_history = {
            (target - timedelta(days=9)).isoformat(): [
                {"entity_id": "Paldi", "cause_category": "gate_outage", "rule": "gate", "severity": "Medium"}
            ],
            (target - timedelta(days=3)).isoformat(): [
                {"entity_id": "Paldi", "cause_category": "gate_outage", "rule": "gate", "severity": "Medium"}
            ],
            (target - timedelta(days=5)).isoformat(): [
                {"entity_id": "Route 58 (Lal Darwaja - Naroda)", "cause_category": "vehicle_breakdowns", "rule": "breakdown", "severity": "Low"}
            ]
        }
        save_history(seed_history)

        gen_demo_data(out_dir=config.DATA_DIR)
        return JSONResponse({
            "status": "ok",
            "demo_date": "2026-10-10",
            "message": "Demo data generated in data/sample/",
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate")
async def generate(
    date_str: str = Form(..., alias="date"),
    metro_daily:     Optional[UploadFile] = File(None),
    metro_incidents: Optional[UploadFile] = File(None),
    brts_daily:      Optional[UploadFile] = File(None),
    amts_daily:      Optional[UploadFile] = File(None),
    weather:         Optional[UploadFile] = File(None),
    events:          Optional[UploadFile] = File(None),
):
    """Accept uploaded CSVs (or use existing data/sample files), run pipeline, return brief_id."""
    # Parse target date
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {date_str}")

    # Save any uploaded files over the demo files
    uploads = {
        "metro_daily.csv":     metro_daily,
        "metro_incidents.csv": metro_incidents,
        "brts_daily.csv":      brts_daily,
        "amts_daily.csv":      amts_daily,
        "weather.csv":         weather,
        "events.csv":          events,
    }
    for fname, upload in uploads.items():
        if upload and upload.filename:
            dest = os.path.join(config.DATA_DIR, fname)
            content = await upload.read()
            if len(content) > 20 * 1024 * 1024:   # 20 MB cap
                raise HTTPException(status_code=400, detail=f"{fname} too large (max 20 MB)")
            with open(dest, "wb") as f:
                f.write(content)

    # Run pipeline
    try:
        result = _run_pipeline(target_date, config.DATA_DIR)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/brief/{brief_id}", response_class=HTMLResponse)
async def view_brief(brief_id: str):
    with _brief_lock:
        html = _briefs.get(brief_id)
    if html is None:
        # Try to read from disk
        path = os.path.join(config.BRIEFS_DIR, f"brief_{brief_id}.html")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                html = f.read()
        else:
            raise HTTPException(status_code=404, detail="Brief not found")
    return HTMLResponse(html)


@app.get("/brief/{brief_id}/download")
async def download_brief(brief_id: str):
    path = os.path.join(config.BRIEFS_DIR, f"brief_{brief_id}.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Brief not found")

    # Embed the CSS inline for a fully standalone file
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "style.css")
    with open(path, encoding="utf-8") as f:
        html = f.read()

    if os.path.exists(css_path):
        with open(css_path, encoding="utf-8") as f:
            css = f.read()
        # Replace the stylesheet link with an inline <style> block
        html = html.replace(
            '<link rel="stylesheet" href="/static/style.css" />',
            f"<style>\n{css}\n</style>",
        )

    from starlette.responses import Response
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="brief_{brief_id}.html"'},
    )


# ── Dev entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import subprocess
    
    print("Building Tailwind CSS...")
    subprocess.run("npx tailwindcss -i ./static/input.css -o ./static/style.css", shell=True, check=True)
    
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
