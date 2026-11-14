"""Run: uvicorn server:app --reload   (then open http://localhost:8000)."""
import json
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Literal
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from kernel import BudgetExhausted, live_llm, live_web
from modes import run_brief
from fixer import run_baseline, run_fix
from runs import Run, RunCancelled, RunRegistry
from router import configure_chaos
from redteam import run_redteam

app = FastAPI(title="Ledger")
class BriefIn(BaseModel):
    company: str = Field("Acme Robotics", min_length=1, max_length=200)
    meeting: str = Field("Thu 3pm", min_length=1, max_length=200)
    cap: int = Field(12000, ge=100, le=1_000_000)
    meeting_at: datetime | None = None
    confidential: bool = False

    @field_validator("company", "meeting")
    @classmethod
    def trim_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

class FixIn(BaseModel):
    repo_path: str
    task: str | None = Field(None, max_length=4000)
    test_cmd: list[str] = Field(default_factory=lambda: ["python", "-m", "pytest"])
    failing_test: str | None = None
    cap: int = Field(6000, ge=100, le=1_000_000)
    confidential: bool = False
    baseline: bool = False
    no_triage: bool = False
    no_tavily: bool = False

    @field_validator("repo_path")
    @classmethod
    def trim_repo_path(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("repo_path must not be blank")
        return value

class RunIn(BaseModel):
    mode: Literal["brief", "fix"]
    params: dict[str, Any] = Field(default_factory=dict)
    confidential: bool = False

class ApprovalIn(BaseModel):
    hash: str = Field(min_length=1)
    decision: Literal["approved", "denied"]
    once: bool = False

class ChaosIn(BaseModel):
    target: str = Field(min_length=1)
    mode: Literal["down", "slow", "429", "off"]

run_registry = RunRegistry(limit=50)
BENCH_SUMMARY_PATH = Path(__file__).parent / "bench" / "results" / "summary.json"


def _execute_run(run: Run, mode: str, params: dict[str, Any], user_id: str):
    try:
        run.check_cancelled()
        if mode == "brief":
            result = run_brief(**params, run=run, user_id=user_id)
        else:
            baseline = params.pop("baseline", False)
            fix_runner = run_baseline if baseline else run_fix
            result = fix_runner(**params, run=run, user_id=user_id)
        if not run.done:
            run.emit("result", result)
    except RunCancelled:
        return
    except Exception as exc:
        run.emit("error", {"message": str(exc)})


@app.exception_handler(BudgetExhausted)
def budget_exhausted(request, exc):
    return JSONResponse(status_code=429, content={"detail": str(exc)})


@app.get("/api/status")
def status():
    bifrost, tavily = live_llm(), live_web()
    return {
        "bifrost": bifrost,
        "tavily": tavily,
        "mode": "live" if bifrost or tavily else "offline",
        "models": {
            "cheap": os.getenv("LEDGER_CHEAP", "openai/gpt-4o-mini"),
            "strong": os.getenv("LEDGER_STRONG", "anthropic/claude-sonnet-4-5"),
        },
    }


@app.get("/api/bench/summary")
def bench_summary():
    try:
        summary = json.loads(BENCH_SUMMARY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="benchmark summary not found") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="benchmark summary is invalid JSON") from exc
    return JSONResponse(content=summary)


@app.post("/api/redteam")
def redteam():
    scenarios = run_redteam()
    return {
        "scenarios": scenarios,
        "passed": sum(scenario["passed"] for scenario in scenarios),
        "failed": sum(not scenario["passed"] for scenario in scenarios),
    }


@app.post("/api/brief")
def brief(b: BriefIn, user_id: str = Header(default="default", alias="X-Ledger-User")):
    return run_brief(
        b.company,
        b.meeting,
        b.cap,
        b.meeting_at,
        user_id=user_id,
        confidential=b.confidential,
    )

@app.post("/api/fix")
def fix(b: FixIn, user_id: str = Header(default="default", alias="X-Ledger-User")):
    return run_fix(**b.model_dump(), user_id=user_id)

@app.post("/api/runs", status_code=202)
def create_run(
    request: RunIn,
    user_id: str = Header(default="default", alias="X-Ledger-User"),
):
    try:
        params = (
            BriefIn(**request.params).model_dump()
            if request.mode == "brief"
            else FixIn(**request.params).model_dump()
        )
        params["confidential"] = params["confidential"] or request.confidential
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_context=False),
        ) from exc
    run = run_registry.create()
    worker = threading.Thread(
        target=_execute_run,
        args=(run, request.mode, params, user_id),
        name=f"ledger-run-{run.id}",
        daemon=True,
    )
    worker.start()
    return {"run_id": run.id}

@app.post("/api/chaos")
def set_chaos(chaos: ChaosIn):
    if os.getenv("LEDGER_DEMO") != "1":
        raise HTTPException(status_code=404, detail="chaos mode is disabled")
    try:
        configure_chaos(chaos.target, chaos.mode)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"target": chaos.target, "mode": chaos.mode}

@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    run = run_registry.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        seq = int(last_event_id) if last_event_id is not None else 0
        if seq < 0:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be a non-negative integer") from exc
    return StreamingResponse(
        run.stream(last_event_id=seq),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = run_registry.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run.id,
        "status": run.status,
        "last_event_id": run.last_event_id,
    }

@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    run = run_registry.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    run.cancel()
    return {"run_id": run.id, "status": run.status}

@app.post("/api/runs/{run_id}/approve")
def approve_run(run_id: str, approval: ApprovalIn):
    run = run_registry.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not run.resolve_approval(approval.hash, approval.decision, approval.once):
        raise HTTPException(status_code=409, detail="no pending approval for this hash")
    return {"run_id": run.id, "hash": approval.hash, "decision": approval.decision}

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))
