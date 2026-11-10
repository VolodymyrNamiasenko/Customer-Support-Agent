"""All records, labels, actor strings and sources here are invented."""
import copy
import hashlib
import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, ValidationError
from langchain_core.documents import Document

from backend.routers import chat, reviews, documents
from backend.services import document_store
from backend.services.reviews import ReviewStore, ReviewConflict
from backend.services.retrieval_trace import retrieve_with_trace, corpus_fingerprint
from evaluation.export_pilot import export_pilot, SCHEMA, validate_snapshot
from evaluation.retrieval_holdout import load_frozen, evaluate_retrieval, recall_at_k, CORPUS, FIXTURE
from pilot_fakes import configure_vector, PROVENANCE, trace


class PilotAcceptance(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ReviewStore(self.root / "private.sqlite3")
        self.vector = Mock()
        configure_vector(self.vector)
        app = FastAPI()
        app.state.vectorstore = self.vector
        app.state.review_store = self.store
        app.state.pilot_provenance = PROVENANCE
        from threading import Lock
        app.state.write_lock = Lock()
        app.include_router(chat.router, prefix="/api")
        app.include_router(reviews.router, prefix="/api/reviews")
        app.include_router(documents.router, prefix="/api/documents")
        self.app = app
        self.client = TestClient(app)

    def completed(self, *, relevant=False):
        row = self.store.begin_attempt("Invented pilot question")
        row = self.store.save_trace(row["id"], row["version"], trace())
        return self.store.finish_attempt(row["id"], row["version"], {
            "answer": "Synthetic answer", "sources": ["synthetic.md"],
            "hallucination_guard": {"is_valid": True, "entity_is_integrated": relevant,
                                    "has_non_creation_signal": relevant}, "context_snippets": []})

    def judge(self, row, correctness="incorrect", bucket="wrong_retrieval"):
        return self.store.expert_verdict(row["id"], row["version"], correctness,
                                         None if correctness == "correct" else bucket,
                                         "Compared invented source", ["synthetic.md#paragraph"])

    def set_policy(self, **overrides):
        with closing(self.store.connect()) as db, db:
            policy = {**self.store.policy(db), **overrides}
            db.execute("UPDATE pilot_settings SET value=? WHERE key='policy'", (json.dumps(policy),))

    def test_one_query_preserves_ids_scores_order_and_context_subset(self):
        self.vector.similarity_search.return_value = [
            Document(page_content="Invented A", metadata={"source": "a.md"}),
            Document(page_content="Invented A", metadata={"source": "copy.md"}),
            Document(page_content="Invented B", metadata={"source": "b.md"})]
        docs, observed = retrieve_with_trace(self.vector, "Invented question", 3, PROVENANCE)
        self.vector._collection.query.assert_called_once()
        self.vector.similarity_search.assert_not_called()
        self.assertEqual([h["rank"] for h in observed["hits"]], [1, 2, 3])
        self.assertEqual([h["score"] for h in observed["hits"]], [0.1] * 3)
        self.assertEqual(observed["used_context_chunk_ids"], ["synthetic-0", "synthetic-2"])
        self.assertEqual(observed["discarded_duplicates"][0]["chunk_id"], "synthetic-1")
        self.assertEqual(len(docs), 2)
        self.assertEqual(observed["provenance"], PROVENANCE)
        self.assertEqual(observed["score_kind"], "distance")
        self.assertTrue(observed["lower_is_more_similar"])

    def test_chat_persists_trace_before_dspy_and_records_guard_replacement(self):
        self.vector.similarity_search.return_value = [Document(page_content="Synthetic source", metadata={"source": "demo.md"})]
        def infer(**kwargs):
            snapshot = self.store.export_snapshot()
            self.assertEqual(len(snapshot["retrieval_traces"]), 1)
            self.assertEqual(snapshot["records"][0]["generation_state"], "generating")
            return SimpleNamespace(reasoning=""), "Guard restriction", SimpleNamespace(
                is_valid=False, entity_is_integrated=True, has_non_creation_signal=True, warning="blocked")
        with patch.object(chat, "run_inference", side_effect=infer):
            response = self.client.post("/api/chat", json={"question": "Synthetic question", "k": 3})
        self.assertEqual(response.status_code, 200, response.text)
        row = self.store.get(response.json()["review_id"])
        self.assertEqual(row["retrieval_trace"]["k"], 3)
        self.assertTrue(row["response"]["guard_replacement"])
        self.assertTrue(row["events"][-1]["data"]["guard_replacement"])

    def test_empty_index_has_trace_and_no_generation(self):
        self.vector._collection.count.return_value = 0
        with patch.object(chat, "run_inference") as infer:
            response = self.client.post("/api/chat", json={"question": "Invented empty query"})
        self.assertEqual(response.status_code, 200)
        row = self.store.get(response.json()["review_id"])
        self.assertEqual(row["retrieval_trace"]["hits"], [])
        self.assertEqual(row["retrieval_trace"]["used_context_chunk_ids"], [])
        infer.assert_not_called()

    def test_llm_failure_retains_trace_and_cannot_be_approved(self):
        self.vector.similarity_search.return_value = [Document(page_content="Synthetic", metadata={"source": "demo.md"})]
        with patch.object(chat, "run_inference", side_effect=RuntimeError("Do not log sensitive exception content")):
            response = self.client.post("/api/chat", json={"question": "Invented failure"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive", response.text)
        row = self.store.get(response.json()["detail"]["review_id"])
        self.assertEqual(row["generation_state"], "failed")
        self.assertEqual(len(row["retrieval_trace"]["hits"]), 1)
        with self.assertRaises(ReviewConflict):
            self.store.update(row["id"], row["version"], "Synthetic reviewer", "", decision="approved")

    def test_retrieval_failure_has_explicit_failed_trace(self):
        self.vector._collection.query.side_effect = RuntimeError("Synthetic unavailable index")
        response = self.client.post("/api/chat", json={"question": "Invented query failure"})
        row = self.store.get(response.json()["detail"]["review_id"])
        self.assertEqual(row["retrieval_trace"]["status"], "failed")
        self.assertEqual(row["generation_state"], "failed")

    def test_question_ownership_routes_high_rating_even_if_generation_guard_misses_it(self):
        self.set_policy(high_sample_probability=0)
        self.vector.similarity_search.return_value = [Document(page_content="Unrelated synthetic guide", metadata={"source": "guide.md"})]
        check = SimpleNamespace(is_valid=True, entity_is_integrated=False, has_non_creation_signal=False, warning="")
        with patch.object(chat, "run_inference", return_value=(SimpleNamespace(reasoning=""), "Invented draft", check)):
            response = self.client.post("/api/chat", json={"question": "Can I manually create a read-only entity?"})
        row = self.store.get(response.json()["review_id"])
        self.store.update(row["id"], row["version"], "Ignored", "", rating=5)
        self.assertIn("guard_relevant_high_satisfaction", self.store.expert_queue()["items"][0]["selection_reasons"])

    def test_satisfaction_and_correctness_have_separate_denominators(self):
        row = self.completed()
        row = self.store.update(row["id"], row["version"], "Invented customer name", "Useful", rating=5)
        self.judge(row)
        self.completed()  # Unrated and unreviewed must not dilute either denominator.
        metrics = self.client.get("/api/reviews/metrics").json()["pilot"]
        self.assertEqual(metrics["satisfaction"], {"N": 1, "mean_rating": 5})
        self.assertEqual(metrics["expert_correctness"]["N_reviewed"], 1)
        self.assertEqual(metrics["expert_correctness"]["correct_fraction"], 0)
        self.assertEqual(metrics["expert_correctness"]["counts"]["incorrect"], 1)
        self.assertNotIn("Invented customer name", self.store.path.read_bytes().decode("latin1"))
        self.assertEqual(self.store.get(row["id"])["rating"], 5)

    def test_zero_reviewed_is_null_and_legacy_is_not_pilot_evidence(self):
        self.store.create("Invented legacy", {"sources": [], "answer": "Legacy", "hallucination_guard": {}})
        stats = self.store.pilot_metrics()
        self.assertIsNone(stats["expert_correctness"]["correct_fraction"])
        self.assertIsNone(stats["satisfaction"]["mean_rating"])
        self.assertEqual(stats["legacy_or_nonpilot_responses"], 1)

    def test_guard_relevant_high_is_mandatory_even_with_zero_random_sample(self):
        self.set_policy(high_sample_probability=0)
        row = self.completed(relevant=True)
        row = self.store.update(row["id"], row["version"], "Ignored identity", "", rating=5)
        low = self.completed()
        self.store.update(low["id"], low["version"], "Ignored", "", rating=1)
        neutral = self.completed()
        self.store.update(neutral["id"], neutral["version"], "Ignored", "", rating=3)
        ordinary = self.completed()
        self.store.update(ordinary["id"], ordinary["version"], "Ignored", "", rating=5)
        queue = self.store.expert_queue()
        self.assertEqual(queue["total"], 2)
        match = next(r for r in queue["items"] if r["id"] == row["id"])
        self.assertIn("guard_relevant_high_satisfaction", match["selection_reasons"])
        # A later rating cannot erase the historical safety selection.
        self.store.update(row["id"], row["version"], "Ignored", "", rating=3)
        self.assertEqual(self.store.expert_queue()["total"], 2)

    def test_ten_percent_sampling_is_stable_across_refresh_and_restart(self):
        self.set_policy(seed="synthetic-sampling-seed")
        expected = set()
        for _ in range(80):
            row = self.completed()
            draw = int(hashlib.sha256(("synthetic-sampling-seed" + row["id"]).encode()).hexdigest(), 16) / 2**256
            if draw < .1:
                expected.add(row["id"])
            self.store.update(row["id"], row["version"], "Ignored", "", rating=4)
        selected = {r["id"] for r in self.store.expert_queue(limit=100)["items"]}
        self.assertEqual(selected, expected)
        restarted = ReviewStore(self.store.path)
        self.assertEqual({r["id"] for r in restarted.expert_queue(limit=100)["items"]}, expected)
        self.assertEqual(self.store.policy()["high_sample_probability"], .1)

    def test_sme_endpoint_and_stale_verdict_do_not_overwrite_history(self):
        row = self.completed()
        body = {"version": row["version"], "correctness": "incorrect", "error_bucket": "unsupported_claim",
                "rationale": "Synthetic contradiction", "evidence": ["synthetic.md#1"]}
        url = f"/api/reviews/{row['id']}/expert-verdict"
        self.assertEqual(self.client.post(url, json=body).status_code, 200)
        self.assertEqual(self.client.post(url, json=body).status_code, 409)
        stored = self.store.get(row["id"])
        self.assertEqual(stored["expert_role"], "Manufacturing Engineer")
        self.assertIsNone(stored["rating"])
        self.assertEqual(sum(e["action"] == "expert_verdict" for e in stored["events"]), 1)

    def test_invalid_expert_bucket_and_missing_evidence_are_rejected(self):
        row = self.completed()
        for correctness, bucket, evidence in [("incorrect", None, ["source"]), ("correct", "wrong_retrieval", ["source"]),
                                               ("correct", None, []), ("incorrect", "unregistered", ["source"])]:
            response = self.client.post(f"/api/reviews/{row['id']}/expert-verdict", json={
                "version": row["version"], "correctness": correctness, "error_bucket": bucket,
                "rationale": "Synthetic", "evidence": evidence})
            self.assertEqual(response.status_code, 422)

    def test_negative_sme_verdict_revokes_prior_release(self):
        row = self.completed()
        row = self.store.update(row["id"], row["version"], "Synthetic release reviewer", "", decision="approved")
        self.assertEqual(self.store.release(row["id"])["id"], row["id"])
        row = self.judge(row)
        with self.assertRaises(ReviewConflict):
            self.store.release(row["id"])
        with self.assertRaises(ReviewConflict):
            self.store.update(row["id"], row["version"], "Synthetic", "", decision="approved")

    def test_audit_and_trace_tables_are_append_only(self):
        row = self.completed()
        for sql in ("UPDATE review_events SET actor='changed'", "DELETE FROM review_events",
                    "UPDATE retrieval_traces SET trace='{}'", "DELETE FROM retrieval_traces"):
            with closing(self.store.connect()) as db, self.assertRaises(sqlite3.IntegrityError):
                db.execute(sql)

    def test_export_schema_relations_metrics_and_privacy(self):
        row = self.completed(relevant=True)
        row = self.store.update(row["id"], row["version"], "Fictional identifying name", "Synthetic feedback", rating=5)
        self.judge(row)
        output = self.root / "private-export.json"
        snapshot = export_pilot(self.store.path, output)
        Draft202012Validator(json.loads(SCHEMA.read_text())).validate(snapshot)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("Fictional identifying name", output.read_text())
        ids = {r["id"] for r in snapshot["records"]}
        for kind in ("review_events", "retrieval_traces", "expert_verdicts", "queue_selections"):
            self.assertTrue(all(r["response_id"] in ids for r in snapshot[kind]))
        self.assertEqual(snapshot["metrics"]["satisfaction"]["mean_rating"], 5)
        self.assertEqual(snapshot["metrics"]["expert_correctness"]["correct_fraction"], 0)
        damaged = copy.deepcopy(snapshot)
        damaged["schema_version"] = "unrecognized"
        with self.assertRaises(ValidationError):
            Draft202012Validator(json.loads(SCHEMA.read_text())).validate(damaged)
        with self.assertRaises(FileExistsError):
            export_pilot(self.store.path, output)
        orphaned = copy.deepcopy(snapshot)
        orphaned["review_events"][0]["response_id"] = "not-present"
        with self.assertRaises(ValueError):
            validate_snapshot(orphaned)

    def test_export_rejects_repository_target(self):
        with self.assertRaises(ValueError):
            export_pilot(self.store.path, Path(__file__).resolve().parents[1] / "private-export.json")

    def test_pilot_document_mutation_requires_reviewed_change_id(self):
        self.app.state.pilot_mode = True
        for patcher in (patch.object(documents, "UPLOAD_DIR", str(self.root / "uploads")),
                        patch.object(document_store, "DOCUMENT_REGISTRY", str(self.root / "registry.json"))):
            patcher.start()
            self.addCleanup(patcher.stop)
        row = self.completed()
        self.store.update(row["id"], row["version"], "Ignored", "Please add material", rating=1)
        response = self.client.post("/api/documents/upload", files={"file": ("invented.md", b"Synthetic only", "text/markdown")})
        self.assertEqual(response.status_code, 409)
        self.vector.add_documents.assert_not_called()

    def evaluated_plan(self, *, bad_candidate=False):
        from backend.services.ingestion import chunk_text
        self.app.state.pilot_mode = True
        for patcher in (patch.object(documents, "UPLOAD_DIR", str(self.root / "uploads")),
                        patch.object(document_store, "DOCUMENT_REGISTRY", str(self.root / "registry.json"))):
            patcher.start()
            self.addCleanup(patcher.stop)
        row = self.judge(self.completed())
        verdict_id = next(e["data"]["verdict_id"] for e in row["events"] if e["action"] == "expert_verdict")
        before = self.store.register_evaluation(evaluate_retrieval(self.vector, PROVENANCE))
        candidate = Mock()
        configure_vector(candidate)
        text = "Different candidate" if bad_candidate else "Invented upload content"
        candidate.similarity_search.return_value = chunk_text(text, "invented.md", "invented.md", "md")
        after = self.store.register_evaluation(evaluate_retrieval(candidate, PROVENANCE))
        plan = {"operation": "upload", "filename": "invented.md",
                "file_sha256": "sha256:" + hashlib.sha256(b"Invented upload content").hexdigest(),
                "before_run": before, "after_run": after, "verdict_id": verdict_id,
                "reason": "Human synthetic corrective proposal", "actor": "Manufacturing Engineer"}
        self.vector.add_documents.side_effect = lambda chunks, ids: setattr(self.vector.similarity_search, "return_value", chunks)
        self.vector.delete.side_effect = lambda ids: setattr(self.vector.similarity_search, "return_value", [])
        return plan, row

    def test_reviewed_upload_logs_human_before_after_evidence(self):
        plan, _ = self.evaluated_plan()
        response = self.client.post("/api/reviews/corpus-changes", json=plan)
        self.assertEqual(response.status_code, 200, response.text)
        identifier = response.json()["change_id"]
        result = self.client.post(f"/api/documents/upload?change_id={identifier}",
                                 files={"file": ("invented.md", b"Invented upload content", "text/markdown")})
        self.assertEqual(result.status_code, 201, result.text)
        snapshot = self.store.export_snapshot()
        change = next(c for c in snapshot["corpus_changes"] if c["id"] == identifier)
        self.assertEqual(change["state"], "applied")
        self.assertIn("before_recall_at_k", change["plan"])
        self.assertIn("after_recall_at_k", change["plan"])
        self.assertEqual([e["action"] for e in snapshot["corpus_change_events"]],
                         ["proposed", "human_apply_started", "applied"])
        Draft202012Validator(json.loads(SCHEMA.read_text())).validate(snapshot)

    def test_changed_candidate_is_rolled_back_and_audited(self):
        plan, _ = self.evaluated_plan(bad_candidate=True)
        identifier = self.store.propose_corpus_change(plan)
        result = self.client.post(f"/api/documents/upload?change_id={identifier}",
                                 files={"file": ("invented.md", b"Invented upload content", "text/markdown")})
        self.assertEqual(result.status_code, 409, result.text)
        self.assertFalse((self.root / "uploads/invented.md").exists())
        self.assertEqual(document_store.load_registry().documents, {})
        self.assertEqual(self.store.export_snapshot()["corpus_changes"][0]["state"], "failed")

    def test_reviewed_delete_logs_before_after_and_removes_only_evaluated_file(self):
        plan, _ = self.evaluated_plan()
        upload = self.store.propose_corpus_change(plan)
        response = self.client.post(f"/api/documents/upload?change_id={upload}",
                                    files={"file": ("invented.md", b"Invented upload content", "text/markdown")})
        self.assertEqual(response.status_code, 201, response.text)
        before = self.store.register_evaluation(evaluate_retrieval(self.vector, PROVENANCE))
        empty = Mock()
        configure_vector(empty)
        after = self.store.register_evaluation(evaluate_retrieval(empty, PROVENANCE))
        deletion = self.store.propose_corpus_change({**plan, "operation": "delete", "file_sha256": None,
                                                    "before_run": before, "after_run": after})
        result = self.client.delete(f"/api/documents/invented.md?change_id={deletion}")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse((self.root / "uploads/invented.md").exists())
        self.assertEqual(document_store.load_registry().documents, {})
        self.assertTrue(all(r["state"] == "applied" for r in self.store.export_snapshot()["corpus_changes"]))

    def test_rating_or_missing_evaluation_cannot_authorize_change(self):
        plan, _ = self.evaluated_plan()
        with self.assertRaises(ReviewConflict):
            self.store.propose_corpus_change({**plan, "verdict_id": 9999})
        with self.assertRaises(ReviewConflict):
            self.store.propose_corpus_change({**plan, "after_run": "missing"})

    def test_new_expert_verdict_invalidates_old_change_proposal(self):
        plan, row = self.evaluated_plan()
        identifier = self.store.propose_corpus_change(plan)
        self.judge(row, correctness="correct")
        with self.assertRaises(ReviewConflict):
            self.store.start_corpus_change(identifier, "upload", plan["filename"], plan["file_sha256"],
                                          corpus_fingerprint(self.vector))

    def test_stale_corpus_and_wrong_file_cannot_apply_plan(self):
        plan, _ = self.evaluated_plan()
        identifier = self.store.propose_corpus_change(plan)
        for filename, fingerprint in [("wrong.md", corpus_fingerprint(self.vector)), ("invented.md", "changed-corpus")]:
            with self.assertRaises(ReviewConflict):
                self.store.start_corpus_change(identifier, "upload", filename, plan["file_sha256"], fingerprint)

    def test_forged_recall_or_changed_gold_cannot_register_as_run(self):
        report = evaluate_retrieval(self.vector, PROVENANCE)
        for broken in [{**report, "fixture_sha256": "unfrozen"}, {**report, "recall_at_k": 1.0}]:
            with self.assertRaises(ValueError):
                self.store.register_evaluation(broken)

    def test_concurrent_expert_verdicts_conflict(self):
        row = self.completed()
        def judge(value):
            try:
                self.judge(row, value)
                return "saved"
            except ReviewConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(judge, ["incorrect", "partially_correct"])), ["saved", "conflict"])


class FrozenRetrievalTests(TestCase):
    def test_frozen_labels_disjoint_dev_and_recall_formula(self):
        fixture, _ = load_frozen()
        self.assertEqual(len(fixture["cases"]), 4)
        self.assertEqual(recall_at_k(["a", "a", "x"], ["a", "b"], 3), .5)
        self.assertEqual(recall_at_k([], ["a"], 3), 0)
        with self.assertRaises(ValueError):
            recall_at_k([], [], 3)

    def test_frozen_fixture_edit_is_detected(self):
        original = FIXTURE.read_bytes()
        with patch.object(Path, "read_bytes", return_value=original + b" "):
            with self.assertRaises(ValueError):
                load_frozen()

    def test_real_chroma_adapter_with_explicit_synthetic_embeddings(self):
        # Integration of Chroma + our adapter, NOT a neural-embedding quality benchmark.
        import chromadb
        client = chromadb.EphemeralClient()
        collection = client.create_collection("synthetic-test-" + __import__("uuid").uuid4().hex,
                                              metadata={"hnsw:space": "cosine"})
        collection.add(ids=["a", "b"], documents=["Invented alpha", "Invented beta"],
                       metadatas=[{"source": "alpha.md"}, {"source": "beta.md"}], embeddings=[[1., 0.], [0., 1.]])
        vector = SimpleNamespace(_collection=collection, _embedding_function=SimpleNamespace(embed_query=lambda q: [1., 0.]))
        docs, observed = retrieve_with_trace(vector, "Invented alpha", 1, PROVENANCE)
        self.assertEqual(observed["hits"][0]["chunk_id"], "a")
        self.assertEqual(observed["used_context_chunk_ids"], ["a"])
        self.assertAlmostEqual(observed["hits"][0]["score"], 0.)
        self.assertEqual(recall_at_k(["a"], ["a"], 1), 1.)
        client.delete_collection(collection.name)


class MigrationTests(TestCase):
    def test_old_database_migrates_idempotently_without_losing_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript("""
                    CREATE TABLE responses (id TEXT PRIMARY KEY, question TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', version INTEGER NOT NULL DEFAULT 1,
                    reviewer TEXT, review_note TEXT, rating INTEGER, feedback TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE review_events (id INTEGER PRIMARY KEY AUTOINCREMENT, response_id TEXT NOT NULL,
                    action TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL);
                    INSERT INTO responses(id,question,payload,created_at,updated_at,rating) VALUES ('old','Invented old question','{}','before','before',4);
                    INSERT INTO review_events(response_id,action,actor,note,version,created_at) VALUES ('old','rated:4','Invented old identity','',1,'before');
                """)
            ReviewStore(path)
            store = ReviewStore(path)
            self.assertEqual(store.get("old")["version"], 1)
            self.assertIsNone(store.get("old")["retrieval_trace"])
            self.assertEqual(store.get("old")["events"][0]["actor"], "anonymous_customer")
            with closing(store.connect()) as db:
                self.assertEqual(db.execute("SELECT actor FROM review_events").fetchone()[0], "Invented old identity")
            exported = store.export_snapshot()
            self.assertEqual(exported["review_events"][0]["actor"], "anonymous_customer")
            self.assertEqual(exported["metrics"]["satisfaction"]["N"], 0)
