"""Private, consistent-snapshot export. Does not upload or publish pilot data."""
import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from backend.services.reviews import ReviewStore
from backend.services.pilot import metrics_for
from evaluation.retrieval_holdout import private_json

SCHEMA = Path(__file__).with_name("pilot_export_v1.schema.json")


def validate_snapshot(snapshot):
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(snapshot)
    records = {r["id"]: r for r in snapshot["records"]}
    if len(records) != len(snapshot["records"]):
        raise ValueError("Duplicate response IDs")
    for table in ("review_events", "retrieval_traces", "expert_verdicts", "queue_selections"):
        for row in snapshot[table]:
            if row["response_id"] not in records:
                raise ValueError("Orphan audit or trace record")
    for event in snapshot["review_events"]:
        if event["version"] > records[event["response_id"]]["version"]:
            raise ValueError("Future event version in snapshot")
    seen = set()
    for row in snapshot["retrieval_traces"]:
        if row["response_id"] in seen:
            raise ValueError("Duplicate response trace")
        seen.add(row["response_id"])
        trace = row["trace"]
        if not set(trace["used_context_chunk_ids"]).issubset({h["chunk_id"] for h in trace["hits"]}):
            raise ValueError("Context references a chunk that was not retrieved")
    if snapshot["metrics"] != metrics_for(snapshot["records"]):
        raise ValueError("Metrics do not match the snapshot denominators")
    changes = {c["id"] for c in snapshot["corpus_changes"]}
    runs = {r["id"] for r in snapshot["evaluation_runs"]}
    if any(e["change_id"] not in changes for e in snapshot["corpus_change_events"]):
        raise ValueError("Orphan corpus change event")
    for change in snapshot["corpus_changes"]:
        if any(change["plan"][key] not in runs for key in ("before_run", "after_run")):
            raise ValueError("Missing corpus evaluation evidence")


def export_pilot(database, output):
    repository = Path(__file__).resolve().parents[1]
    if Path(output).resolve().is_relative_to(repository):
        raise ValueError("Export outside the repository to a private directory")
    if not Path(database).is_file():
        raise ValueError("Existing review database required")
    snapshot = ReviewStore(database).export_snapshot()
    validate_snapshot(snapshot)
    private_json(output, snapshot)
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    snapshot = export_pilot(args.database, args.output)
    print(json.dumps({"schema_version": snapshot["schema_version"], "records": len(snapshot["records"]),
                      "output": args.output, "private": True}))


if __name__ == "__main__":
    main()
