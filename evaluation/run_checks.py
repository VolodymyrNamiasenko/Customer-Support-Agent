"""Synthetic rule checks; optional explicit local inference smoke test."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from backend.hallucination_guard import validate_response


def evaluate(cases):
    results = []
    for case in cases:
        allowed = validate_response(case["context"], case["answer"]).is_valid
        results.append(
            {
                "case": case["name"],
                "passed": allowed == case["expected_allowed"],
                "observed_allowed": allowed,
            }
        )
    return {
        "mode": "synthetic_rule_checks",
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "results": results,
        "scope": "Rule behavior only; not model accuracy or workplace-pilot evidence.",
    }


def live_smoke(base):
    parsed = urlsplit(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "The live smoke check accepts only a local HTTP application URL."
        )
    request = Request(
        base.rstrip("/") + "/api/chat",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(
            {"question": "Can Demo Orders be created directly in MES?", "k": 5}
        ).encode(),
    )
    with urlopen(request, timeout=120) as response:
        body = json.load(response)
    checks = {
        "retrieved_sources_present": bool(body.get("sources")),
        "review_draft_created": bool(body.get("review_id"))
        and body.get("review_status") == "pending",
        "rule_result_returned": isinstance(
            body.get("hallucination_guard", {}).get("is_valid"), bool
        ),
    }
    return {
        "mode": "live_local_smoke",
        "checks": checks,
        "passed": all(checks.values()),
        "scope": "Checks API/model wiring against an indexed synthetic guide, not semantic correctness.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-local-url")
    args = parser.parse_args()
    if args.live_local_url:
        result = live_smoke(args.live_local_url)
        success = result["passed"]
    else:
        result = evaluate(
            json.loads(Path(__file__).with_name("cases.json").read_text())
        )
        success = result["passed"] == result["cases"]
    print(json.dumps(result, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
