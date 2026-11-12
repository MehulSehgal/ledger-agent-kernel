"""Run: uvicorn server:app --reload   (then open http://localhost:8000)."""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from kernel import live_llm, live_web
from modes import run_brief, run_fix

app = FastAPI(title="Ledger")
class BriefIn(BaseModel):
    company: str = Field("Acme Robotics", min_length=1, max_length=200)
    meeting: str = Field("Thu 3pm", min_length=1, max_length=200)
    cap: int = Field(12000, ge=100, le=1_000_000)

    @field_validator("company", "meeting")
    @classmethod
    def trim_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

class FixIn(BaseModel):
    cap: int = Field(6000, ge=100, le=1_000_000)

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
@app.post("/api/brief")
def brief(b: BriefIn): return run_brief(b.company, b.meeting, b.cap)
@app.post("/api/fix")
def fix(b: FixIn): return run_fix(b.cap)
app.mount("/", StaticFiles(directory=Path(__file__).parent, html=True))
