"""In-memory run lifecycle and event streaming primitives."""
import json
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone


EVENT_TYPES = {
    "step",
    "model_call",
    "failover",
    "budget",
    "claim",
    "approval_request",
    "approval_result",
    "blocked",
    "result",
    "error",
}


class RunCancelled(Exception):
    """Raised when a run reaches a cancellation checkpoint."""


class _Approval:
    def __init__(self):
        self.event = threading.Event()
        self.decision = None
        self.once = False
        self.requested = False


class Run:
    def __init__(self, id=None, events=None, lock=None):
        self.id = id or str(uuid.uuid4())
        self.events = events if events is not None else []
        self.lock = lock or threading.RLock()
        self._condition = threading.Condition(self.lock)
        self._seq = max((item.get("seq", 0) for item in self.events), default=0)
        self._done = False
        self._status = "running"
        self.cancelled = threading.Event()
        self._approvals = {}
        self._cache = {}
        self.approval_channel = False

    def _emit_locked(self, event_type, data):
        if self._done:
            return None
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported run event type: {event_type}")
        if not isinstance(data, dict):
            raise TypeError("run event data must be an object")
        self._seq += 1
        event = {
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "data": data,
        }
        self.events.append(event)
        if event_type == "result":
            self._done = True
            self._status = "completed"
        elif event_type == "error":
            self._done = True
            self._status = "failed"
        self._condition.notify_all()
        return event

    def emit(self, event_type, data):
        with self._condition:
            return self._emit_locked(event_type, data)

    @property
    def status(self):
        with self.lock:
            return self._status

    @property
    def done(self):
        with self.lock:
            return self._done

    @property
    def last_event_id(self):
        with self.lock:
            return self._seq

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise RunCancelled("run cancelled")

    def cancel(self):
        with self._condition:
            if self._done:
                return False
            self.cancelled.set()
            for approval_hash, approval in self._approvals.items():
                if approval.decision is None:
                    approval.decision = "denied"
                    approval.once = False
                    approval.event.set()
                    self._emit_locked("approval_result", {
                        "hash": approval_hash,
                        "decision": "denied",
                        "once": False,
                    })
            self._emit_locked("step", {
                "id": "cancel",
                "title": "Run cancellation",
                "status": "skipped",
                "detail": "Run cancelled",
            })
            self._status = "cancelled"
            self._done = True
            for approval in self._approvals.values():
                if approval.decision is None:
                    approval.decision = "denied"
                    approval.event.set()
            self._condition.notify_all()
            return True

    def wait_for_approval(
        self,
        hash,
        timeout=300,
        kind="NETWORK",
        summary="Approval requested",
        payload=None,
        risk="unspecified",
    ):
        with self._condition:
            if self._done:
                return "denied"
            approval = self._approvals.setdefault(hash, _Approval())
            if not approval.requested:
                approval.requested = True
                self._emit_locked("approval_request", {
                    "hash": hash,
                    "kind": kind,
                    "summary": summary,
                    "payload": payload if payload is not None else {},
                    "risk": risk,
                })
        if not approval.event.wait(timeout):
            with self._condition:
                if approval.decision is None:
                    approval.decision = "denied"
                    approval.once = False
                    approval.event.set()
                    self._emit_locked("approval_result", {
                        "hash": hash,
                        "decision": "denied",
                        "once": False,
                    })
        with self.lock:
            return approval.decision or "denied"

    def consume_approval(self, hash):
        with self._condition:
            approval = self._approvals.get(hash)
            if approval is None or approval.decision != "approved":
                return False
            if approval.once:
                del self._approvals[hash]
            return True

    def resolve_approval(self, hash, decision, once=False):
        if decision not in ("approved", "denied"):
            raise ValueError("decision must be approved or denied")
        with self._condition:
            approval = self._approvals.get(hash)
            if self._done or approval is None or approval.decision is not None:
                return False
            approval.decision = decision
            approval.once = bool(once)
            approval.event.set()
            self._emit_locked("approval_result", {
                "hash": hash,
                "decision": decision,
                "once": bool(once),
            })
            return True

    def get_cached(self, key):
        with self.lock:
            return self._cache.get(key)

    def set_cached(self, key, value):
        with self.lock:
            self._cache[key] = value

    def events_after(self, seq, timeout=None):
        with self._condition:
            if not any(item["seq"] > seq for item in self.events) and not self._done:
                self._condition.wait(timeout)
            return [item for item in self.events if item["seq"] > seq], self._done

    def stream(self, last_event_id=0, heartbeat=15):
        seq = last_event_id
        while True:
            events, done = self.events_after(seq, heartbeat)
            if not events:
                if done:
                    return
                yield ": heartbeat\n\n"
                continue
            for event in events:
                seq = event["seq"]
                data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {seq}\nevent: {event['type']}\ndata: {data}\n\n"
            if done and seq >= self.last_event_id:
                return


class NullRun:
    """No-op run target for existing synchronous calls."""

    def emit(self, event_type, data):
        return None

    def check_cancelled(self):
        return None

    def cancel(self):
        return False

    def wait_for_approval(self, hash, timeout, **kwargs):
        return "denied"

    def resolve_approval(self, hash, decision, once=False):
        return False

    def consume_approval(self, hash):
        return False

    def get_cached(self, key):
        return None

    def set_cached(self, key, value):
        return None


class RunRegistry:
    def __init__(self, limit=50):
        if limit < 1:
            raise ValueError("run registry limit must be positive")
        self.limit = limit
        self._runs = OrderedDict()
        self._lock = threading.Lock()

    def add(self, run):
        with self._lock:
            if run.id in self._runs:
                raise ValueError(f"run already registered: {run.id}")
            while len(self._runs) >= self.limit:
                _, oldest = self._runs.popitem(last=False)
                oldest.cancel()
            run.approval_channel = True
            self._runs[run.id] = run
        return run

    def create(self):
        return self.add(Run())

    def get(self, run_id):
        with self._lock:
            return self._runs.get(run_id)

    def __len__(self):
        with self._lock:
            return len(self._runs)
NULL_RUN = NullRun()
