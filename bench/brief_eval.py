"""Run the Brief pipeline over a fixed set of eight hand-labelable companies."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from modes import run_brief


RESULTS_DIR = Path(__file__).resolve().parent / "results"
COMPANIES = (
    "Acme Robotics",
    "Northstar Analytics",
    "Cedar Health",
    "Bluebird Logistics",
    "Summit Energy",
    "Harbor Systems",
    "Pioneer Materials",
    "Redwood Software",
)


class _CaptureRun:
    def __init__(self):
        self.events = []

    def emit(self, event_type, data):
        self.events.append({"type": event_type, "data": data})

    def check_cancelled(self):
        return None


def evaluate_briefs(companies=COMPANIES, output_dir=RESULTS_DIR):
    companies = tuple(companies)
    if len(companies) != 8 or any(not isinstance(company, str) or not company.strip() for company in companies):
        raise ValueError("brief evaluation requires exactly eight non-empty company names")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    labels = []
    verified = 0
    rejected_by_reason = Counter()
    for company in companies:
        run = _CaptureRun()
        run_brief(company, "Brief evaluation", run=run)
        for event in run.events:
            if event["type"] != "claim":
                continue
            claim = event["data"]
            status = claim.get("status")
            if status == "verified":
                verified += 1
            elif status == "rejected":
                rejected_by_reason[claim.get("reason") or "unspecified"] += 1
            else:
                continue
            labels.append({
                "company": company,
                "claim": claim.get("text", ""),
                "status": status,
                "reason": claim.get("reason") or "",
                "correct?": "",
            })

    rejected = sum(rejected_by_reason.values())
    report = {
        "companies": list(companies),
        "verified": verified,
        "rejected": rejected,
        "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
        "counts": {
            "verified": verified,
            "rejected": rejected,
            "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
        },
    }
    csv_path = output_dir / "brief_labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=("company", "claim", "status", "reason", "correct?"),
        )
        writer.writeheader()
        writer.writerows(labels)
    (output_dir / "brief_eval.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()
    print(json.dumps(evaluate_briefs(output_dir=args.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
