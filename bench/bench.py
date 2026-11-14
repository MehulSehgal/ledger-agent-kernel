"""Run and summarize reproducible Fix-mode benchmark trials."""
import argparse
import hashlib
import json
import math
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, NormalDist

from fixer import IGNORED_DIRECTORIES, validate_test_cmd


ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "bench" / "tasks"
RESULTS_DIR = ROOT / "bench" / "results"
RUNS_PATH = RESULTS_DIR / "runs.jsonl"
SUMMARY_PATH = RESULTS_DIR / "summary.json"
ARMS = ("baseline", "ledger", "ledger_no_triage", "ledger_no_tavily")
_APPROVAL_POLL_SECONDS = 0.01
_TRIAL_TIMEOUT_SECONDS = 600


def load_tasks(max_tasks=10):
    if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 1:
        raise ValueError("max_tasks must be a positive integer")
    tasks = []
    seen = set()
    for metadata_path in sorted(TASKS_DIR.glob("*/task.json")):
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        required = {"id", "repo_dir", "test_cmd", "failing_test", "source"}
        if not isinstance(data, dict) or set(data) != required:
            raise ValueError(f"{metadata_path} must contain exactly {sorted(required)}")
        if not all(isinstance(data[key], str) and data[key].strip() for key in (
            "id", "repo_dir", "failing_test", "source",
        )):
            raise ValueError(f"{metadata_path} has a blank or invalid required field")
        if data["source"] not in ("real", "seeded"):
            raise ValueError(f"{metadata_path}: source must be 'real' or 'seeded'")
        if data["id"] in seen:
            raise ValueError(f"duplicate benchmark task id: {data['id']}")
        seen.add(data["id"])
        task_dir = metadata_path.parent.resolve(strict=True)
        repo_dir = (task_dir / data["repo_dir"]).resolve(strict=True)
        try:
            repo_dir.relative_to(task_dir)
        except ValueError as exc:
            raise ValueError(f"{metadata_path}: repo_dir must stay inside its task directory") from exc
        if not repo_dir.is_dir():
            raise ValueError(f"{metadata_path}: repo_dir must be a directory")
        data["test_cmd"] = validate_test_cmd(data["test_cmd"])
        data["repo_dir"] = repo_dir
        data["metadata_path"] = metadata_path
        tasks.append(data)
        if len(tasks) == max_tasks:
            break
    return tasks


def _known_sum(values):
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def build_record(arm, task, run_number, result, events, seconds):
    receipt = result.get("receipt") or {}
    calls = receipt.get("calls") or []
    model_events = [event for event in events if event.get("type") == "model_call"]
    token_events = [event.get("data") or {} for event in model_events]
    model_names = {
        call["model"] for call in calls
        if isinstance(call, dict) and isinstance(call.get("model"), str)
    }
    model_names.update(
        event["data"]["model"]
        for event in model_events
        if isinstance(event.get("data", {}).get("model"), str)
    )
    return {
        "arm": arm,
        "task_id": task["id"],
        "run": run_number,
        "pass": result.get("status") == "green",
        "tokens_in": _known_sum([item.get("tokens_in") for item in token_events]),
        "tokens_out": _known_sum([item.get("tokens_out") for item in token_events]),
        "tokens_cached": _known_sum([item.get("tokens_cached") for item in token_events]),
        "usd": receipt.get("usd"),
        "seconds": seconds,
        "attempts": sum(
            1 for step in result.get("steps", [])
            if str(step.get("step", "")).startswith("Apply attempt ")
        ),
        "failovers": sum(1 for event in events if event.get("type") == "failover"),
        "models_used": sorted(model_names),
        "date": datetime.now(timezone.utc).date().isoformat(),
    }


def wilson_interval(successes, n, confidence=0.95):
    if n <= 0:
        return None
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    proportion = successes / n
    denominator = 1 + z * z / n
    center = (proportion + z * z / (2 * n)) / denominator
    radius = (
        z * math.sqrt(proportion * (1 - proportion) / n + z * z / (4 * n * n))
        / denominator
    )
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _percentile(sorted_values, quantile):
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _bootstrap_mean(values, seed, samples):
    if not values:
        return {"mean": None, "ci95": None}
    rng = random.Random(seed)
    count = len(values)
    estimates = sorted(
        mean(rng.choices(values, k=count))
        for _ in range(samples)
    )
    return {
        "mean": mean(values),
        "ci95": [_percentile(estimates, 0.025), _percentile(estimates, 0.975)],
    }


def summarize_records(records, bootstrap_samples=2000):
    if isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int) or bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be a positive integer")
    grouped = {}
    for record in records:
        arm = record.get("arm")
        if not isinstance(arm, str) or not arm:
            raise ValueError("each benchmark record must have a non-empty arm")
        grouped.setdefault(arm, []).append(record)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "arms": {},
    }
    for arm, rows in sorted(grouped.items()):
        passed = sum(bool(row.get("pass")) for row in rows)
        costs = [row.get("usd") for row in rows]

        def metric(values, suffix):
            observed = [
                value for value in values
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value)
            ]
            seed = int.from_bytes(
                hashlib.sha256(f"{arm}:{suffix}".encode("utf-8")).digest()[:8],
                "big",
            )
            return _bootstrap_mean(observed, seed, bootstrap_samples)

        known_costs = [
            value for value in costs
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value)
        ]
        complete_costs = len(known_costs) == len(rows)
        mean_usd = (
            metric(known_costs, "usd")
            if complete_costs
            else {"mean": None, "ci95": None}
        )
        summary["arms"][arm] = {
            "n": len(rows),
            "passes": passed,
            "pass_rate": passed / len(rows) if rows else None,
            "pass_rate_ci95": wilson_interval(passed, len(rows)),
            "mean_tokens_in": metric([row.get("tokens_in") for row in rows], "tokens_in"),
            "mean_tokens_out": metric([row.get("tokens_out") for row in rows], "tokens_out"),
            "mean_tokens_cached": metric([row.get("tokens_cached") for row in rows], "tokens_cached"),
            "mean_usd": mean_usd,
            "cost_per_verified_outcome": (
                sum(known_costs) / passed
                if len(known_costs) == len(rows) and passed else None
            ),
        }
    return summary


def _arm_parameters(arm):
    if arm not in ARMS:
        raise ValueError(f"unknown benchmark arm: {arm}")
    return {
        "baseline": arm == "baseline",
        "no_triage": arm == "ledger_no_triage",
        "no_tavily": arm == "ledger_no_tavily",
    }


def _copy_task_repo(source, destination):
    ignored = {name.casefold() for name in IGNORED_DIRECTORIES}

    def ignore(directory, names):
        return [
            name for name in names
            if name.casefold() in ignored or (Path(directory) / name).is_symlink()
        ]

    shutil.copytree(source, destination, ignore=ignore)


def _run_trial(task, arm):
    from fastapi.testclient import TestClient

    import server

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ledger-bench-") as temporary:
        temporary_root = Path(temporary).resolve()
        sandbox = temporary_root / "repo"
        _copy_task_repo(task["repo_dir"], sandbox)

        previous_roots = os.environ.get("LEDGER_ALLOWED_ROOTS")
        roots = [item for item in (previous_roots or "").split(os.pathsep) if item]
        roots.append(str(temporary_root))
        os.environ["LEDGER_ALLOWED_ROOTS"] = os.pathsep.join(roots)
        run = None
        try:
            params = {
                "repo_path": str(sandbox),
                "task": f"Repair benchmark task {task['id']}",
                "test_cmd": task["test_cmd"],
                "failing_test": task["failing_test"],
                **_arm_parameters(arm),
            }
            with TestClient(server.app) as client:
                response = client.post(
                    "/api/runs",
                    json={"mode": "fix", "params": params},
                )
                response.raise_for_status()
                run_id = response.json()["run_id"]
                run = server.run_registry.get(run_id)
                if run is None:
                    raise RuntimeError(f"benchmark run {run_id} was not registered")
                approved_requests = set()
                deadline = time.monotonic() + _TRIAL_TIMEOUT_SECONDS
                while not run.done and time.monotonic() < deadline:
                    with run.lock:
                        pending = [
                            (event["seq"], event["data"]["hash"])
                            for event in run.events
                            if event["type"] == "approval_request"
                            and event["seq"] not in approved_requests
                        ]
                    for sequence, action_hash in pending:
                        approval = client.post(
                            f"/api/runs/{run_id}/approve",
                            json={
                                "hash": action_hash,
                                "decision": "approved",
                                "once": True,
                            },
                        )
                        approval.raise_for_status()
                        approved_requests.add(sequence)
                    time.sleep(_APPROVAL_POLL_SECONDS)
                if not run.done:
                    run.cancel()
                    raise TimeoutError(
                        f"benchmark run {run_id} exceeded {_TRIAL_TIMEOUT_SECONDS} seconds"
                    )
                with run.lock:
                    events = list(run.events)
                result_event = next(
                    (event for event in reversed(events) if event["type"] == "result"),
                    None,
                )
                error_event = next(
                    (event for event in reversed(events) if event["type"] == "error"),
                    None,
                )
                result = result_event["data"] if result_event else {
                    "status": "error",
                    "message": error_event["data"].get("message") if error_event else run.status,
                    "steps": [],
                    "receipt": {"calls": [], "usd": None},
                }
        finally:
            if run is not None and not run.done:
                run.cancel()
            if previous_roots is None:
                os.environ.pop("LEDGER_ALLOWED_ROOTS", None)
            else:
                os.environ["LEDGER_ALLOWED_ROOTS"] = previous_roots
    return result, events, time.monotonic() - started


def _append_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def _read_records(path):
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {path} line {line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"expected an object in {path} line {line_number}")
            records.append(record)
    return records


def run_benchmark(arms=ARMS, runs=3, max_tasks=10, execute_trial=None,
                  runs_path=RUNS_PATH):
    if isinstance(runs, bool) or not isinstance(runs, int) or runs < 1:
        raise ValueError("runs must be a positive integer")
    arms = list(arms)
    if not arms or len(set(arms)) != len(arms):
        raise ValueError("arms must be a non-empty list without duplicates")
    for arm in arms:
        _arm_parameters(arm)
    tasks = load_tasks(max_tasks=max_tasks)
    if not tasks:
        raise ValueError(f"no benchmark tasks found under {TASKS_DIR}")
    execute_trial = execute_trial or _run_trial
    records = []
    for arm in arms:
        for task in tasks:
            for run_number in range(1, runs + 1):
                result, events, seconds = execute_trial(task, arm)
                record = build_record(
                    arm,
                    task,
                    run_number,
                    result,
                    events,
                    seconds,
                )
                _append_record(runs_path, record)
                records.append(record)
    return records


def write_summary(records, summary_path=SUMMARY_PATH, bootstrap_samples=2000):
    summary = summarize_records(records, bootstrap_samples=bootstrap_samples)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = summary_path.with_name(summary_path.name + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, summary_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return summary


def _parser():
    parser = argparse.ArgumentParser(prog="python -m bench")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run benchmark task arms")
    run_parser.add_argument("--arms", default=",".join(ARMS))
    run_parser.add_argument("--runs", type=int, default=3)
    run_parser.add_argument("--max-tasks", type=int, default=10)
    commands.add_parser("summarize", help="summarize recorded benchmark trials")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "run":
        arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
        run_benchmark(arms=arms, runs=args.runs, max_tasks=args.max_tasks)
        records = _read_records(RUNS_PATH)
        summary = write_summary(records)
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        records = _read_records(RUNS_PATH)
        summary = write_summary(records)
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
