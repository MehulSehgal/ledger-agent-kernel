"""Run: uvicorn server:app --reload   (then open http://localhost:8000)."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from kernel import live_llm, live_web
from modes import run_brief, run_fix

app = FastAPI(title="Ledger")
class BriefIn(BaseModel): company: str = "Acme Robotics"; meeting: str = "Thu 3pm"; cap: int = 12000
class FixIn(BaseModel): cap: int = 6000

@app.get("/api/status")
def status(): return {"bifrost": live_llm(), "tavily": live_web()}
@app.post("/api/brief")
def brief(b: BriefIn): return run_brief(b.company, b.meeting, b.cap)
@app.post("/api/fix")
def fix(b: FixIn): return run_fix(b.cap)
app.mount("/", StaticFiles(directory=Path(__file__).parent, html=True))
