import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from backend.hallucination_guard import validate_response
from backend.routers import chat, reviews
from backend.services.reviews import ReviewConflict, ReviewStore
from pilot_fakes import configure_vector, PROVENANCE


class ReviewWorkflowTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "reviews.sqlite3"
        self.store = ReviewStore(self.path)
        app = FastAPI()
        app.state.review_store = self.store
        self.vector = Mock()
        configure_vector(self.vector)
        app.state.pilot_provenance = PROVENANCE
        app.state.vectorstore = self.vector
        app.include_router(chat.router, prefix="/api")
        app.include_router(reviews.router, prefix="/api/reviews")
        self.client = TestClient(app)
        self.payload = {
            "answer": "Use the source system.",
            "sources": ["demo.md"],
            "hallucination_guard": {"is_valid": True},
            "context_snippets": [],
        }

    def create(self, **overrides):
        return self.store.create("Invented question", {**self.payload, **overrides})

    def test_persistent_review_rating_revoke_and_release(self):
        self.assertEqual(self.client.get("/api/reviews/metrics").json()["total"], 0)
        row = self.create()
        identifier = row["id"]
        self.assertEqual(
            self.client.get(f"/api/reviews/{identifier}/release").status_code, 409
        )
        decision = self.client.post(
            f"/api/reviews/{identifier}/decision",
            json={
                "version": 1,
                "actor": "Demo reviewer",
                "decision": "approved",
                "note": "Checked source",
            },
        )
        self.assertEqual(decision.status_code, 200, decision.text)
        released = self.client.get(f"/api/reviews/{identifier}/release").json()
        self.assertEqual(released["answer"], self.payload["answer"])
        self.assertEqual(released["reviewer"], "Demo reviewer")
        rating = self.client.post(
            f"/api/reviews/{identifier}/rating",
            json={
                "version": 2,
                "actor": "Demo reviewer",
                "rating": 4,
                "note": "Useful with source",
            },
        )
        self.assertEqual(rating.status_code, 200, rating.text)
        self.assertEqual(
            self.client.get(f"/api/reviews/{identifier}/release").json()["reviewed_at"],
            released["reviewed_at"],
        )
        restarted = ReviewStore(self.path).get(identifier)
        self.assertEqual(restarted["status"], "approved")
        self.assertEqual(restarted["rating"], 4)
        self.assertEqual(
            [e["action"] for e in restarted["events"]][:3],
            ["generated", "approved", "rated:4"],
        )
        self.assertEqual(
            {k: v for k, v in self.client.get("/api/reviews/metrics").json().items() if k != "pilot"},
            {
                "total": 1,
                "pending": 0,
                "approved": 1,
                "rejected": 0,
                "rated_responses": 1,
                "mean_rating": 4.0,
            },
        )
        self.store.update(
            identifier, 3, "Demo reviewer", "Needs correction", decision="rejected"
        )
        self.assertEqual(
            self.client.get(f"/api/reviews/{identifier}/release").status_code, 409
        )

    def test_failed_checks_or_missing_evidence_cannot_be_approved(self):
        for changes in [{"sources": []}, {"hallucination_guard": {"is_valid": False}}]:
            row = self.create(**changes)
            result = self.client.post(
                f"/api/reviews/{row['id']}/decision",
                json={"version": 1, "actor": "Demo", "decision": "approved"},
            )
            self.assertEqual(result.status_code, 409)
            self.assertEqual(len(self.store.get(row["id"])["events"]), 1)

    def test_stale_and_concurrent_decisions_do_not_overwrite_each_other(self):
        row = self.create()

        def decision(value):
            try:
                self.store.update(row["id"], 1, "Demo", "", decision=value)
                return "saved"
            except ReviewConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(decision, ["approved", "rejected"]))
        self.assertCountEqual(outcomes, ["saved", "conflict"])
        self.assertEqual(self.store.get(row["id"])["version"], 2)

    def test_rating_validation_and_missing_record(self):
        row = self.create()
        for invalid in [0, 6, "5", True]:
            result = self.client.post(
                f"/api/reviews/{row['id']}/rating",
                json={"version": 1, "actor": "Demo", "rating": invalid},
            )
            self.assertEqual(result.status_code, 422)
        self.assertEqual(self.client.get("/api/reviews/missing").status_code, 404)
        self.assertEqual(
            self.client.post(
                f"/api/reviews/{row['id']}/decision",
                json={"version": 1, "actor": " ", "decision": "approved"},
            ).status_code,
            422,
        )

    def test_filters_and_pagination(self):
        a = self.create()
        self.create()
        self.store.update(a["id"], 1, "Demo", "", decision="rejected")
        self.assertEqual(
            self.client.get("/api/reviews?status=rejected").json()["total"], 1
        )
        self.assertEqual(
            len(self.client.get("/api/reviews?limit=1&offset=1").json()["items"]), 1
        )
        self.assertEqual(self.client.get("/api/reviews?limit=101").status_code, 422)

    def test_generated_chat_is_queued_and_missing_evidence_is_persisted(self):
        self.vector.similarity_search.return_value = [
            Document(
                page_content="Demo Orders are read-only and imported from SAP.",
                metadata={"source": "demo.md"},
            )
        ]
        answer = "Demo Orders cannot be manually created."
        guard = validate_response(
            "Demo Orders are read-only and imported from SAP.", answer
        )
        with patch.object(
            chat,
            "run_inference",
            return_value=(SimpleNamespace(reasoning=""), answer, guard),
        ):
            result = self.client.post(
                "/api/chat", json={"question": "Can I create Demo Orders?"}
            )
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["review_status"], "pending")
        self.assertEqual(
            self.store.get(body["review_id"])["response"]["answer"], answer
        )
        self.vector.similarity_search.return_value = []
        self.client.post("/api/chat", json={"question": "No evidence?"})
        self.assertEqual(self.store.metrics()["total"], 2)
