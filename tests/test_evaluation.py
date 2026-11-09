import json
from pathlib import Path
from unittest import TestCase

from evaluation.run_checks import evaluate, live_smoke


class EvaluationTests(TestCase):
    def test_synthetic_cases_match_reviewed_labels(self):
        cases = json.loads(
            (Path(__file__).resolve().parents[1] / "evaluation/cases.json").read_text()
        )
        report = evaluate(cases)
        self.assertEqual(report["passed"], report["cases"], report)

    def test_failure_is_reported_not_relabelled_as_success(self):
        report = evaluate(
            [
                {
                    "name": "deliberate mismatch",
                    "context": "Help page",
                    "answer": "Open Help.",
                    "expected_allowed": False,
                }
            ]
        )
        self.assertEqual(report["passed"], 0)

    def test_live_check_cannot_target_remote_or_credentialed_urls(self):
        for url in [
            "https://example.com",
            "http://user:pass@localhost",
            "http://localhost.example.com",
        ]:
            with self.assertRaises(ValueError):
                live_smoke(url)
