import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from datetime import date, timedelta
from kernel import Meter, BudgetExhausted, verify
from modes import run_brief, run_fix

T = date.today()
SRC = {"date": (T - timedelta(3)).isoformat(), "text": "Acme closed a $60 million Series C round."}

def test_verify_pass():
    assert verify({"claim": "Acme raised $60 million", "quote": "closed a $60 million Series C"}, SRC, T) is None

def test_verify_rejects():
    assert verify({"claim": "x", "quote": "never said this anywhere"}, SRC, T) == "quote not found in source text"
    assert "number 90" in verify({"claim": "raised 90", "quote": "closed a $60 million Series C"}, SRC, T)
    assert verify({"claim": "x", "quote": "Acme closed"}, dict(SRC, date=(T - timedelta(45)).isoformat()), T) == "source date outside window"
    assert verify({"claim": "x", "quote": "Acme closed"}, None, T) == "source not in fetched set"

def test_budget_degrade_and_cap():
    m = Meter(100); assert m.pick("strong") == "strong"
    m.log("a", "cheap", 80, 0); assert m.pick("strong") == "cheap"
    m.log("b", "cheap", 30, 0)
    try: m.pick("cheap"); assert False
    except BudgetExhausted: pass

def test_brief_gate():
    r = run_brief("Acme Robotics", "Thu 3pm")
    assert len(r["audit"]["rejected"]) == 2 and len(r["audit"]["pre_dropped"]) == 2 and r["bullets"]

def test_fix_goes_green():
    assert run_fix()["status"] == "green"
