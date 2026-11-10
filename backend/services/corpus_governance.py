"""Human-reviewed change journal; ratings never authorize corpus mutations."""
import json
import uuid
from contextlib import closing
from backend.services.pilot import conflict, dumps


class CorpusGovernanceMixin:
    def register_evaluation(self, report):
        from evaluation.retrieval_holdout import load_frozen, FIXTURE, recall_at_k
        fixture, manifest = load_frozen()
        if (report.get("mode") != "chroma_retrieval" or report.get("schema_version") != "1.0" or
                report.get("fixture_sha256") != manifest["sha256"][FIXTURE.name] or
                report.get("fixture_version") != fixture["version"] or
                type(report.get("k")) is not int or type(report.get("N")) is not int or
                report.get("k") != fixture["k"] or report.get("N") != len(fixture["cases"])):
            raise ValueError("A matching frozen held-out retrieval run is required")
        results = report.get("results", [])
        if len(results) != len(fixture["cases"]):
            raise ValueError("Incomplete evaluation run")
        values = []
        for case, result in zip(fixture["cases"], results):
            value = recall_at_k(result["retrieved_ids"], case["relevant_ids"], fixture["k"])
            if result["case_id"] != case["id"] or result["relevant_ids"] != case["relevant_ids"] or result["recall_at_k"] != value:
                raise ValueError("Evaluation labels/results do not match frozen benchmark")
            values.append(value)
        if report["recall_at_k"] != sum(values) / len(values) or not report.get("corpus_fingerprint"):
            raise ValueError("Invalid recall or corpus fingerprint")
        identifier = str(uuid.uuid4())
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO evaluation_runs VALUES (?,?,?)", (identifier, dumps(report), self.now()))
        return identifier

    def propose_corpus_change(self, plan):
        required = {"operation", "filename", "file_sha256", "before_run", "after_run", "verdict_id", "reason", "actor"}
        if set(plan) != required or plan["operation"] not in ("upload", "delete", "retrieval_config"):
            raise ValueError("Invalid change plan")
        if not plan["actor"].strip() or not plan["reason"].strip():
            raise ValueError("Human actor and reason required")
        with closing(self.connect()) as db, db:
            verdict = db.execute("SELECT * FROM expert_verdicts WHERE id=?", (plan["verdict_id"],)).fetchone()
            if verdict is None or verdict["correctness"] == "correct":
                conflict("A corrective expert verdict is required; a satisfaction rating is not sufficient")
            reports = []
            for key in ("before_run", "after_run"):
                row = db.execute("SELECT report FROM evaluation_runs WHERE id=?", (plan[key],)).fetchone()
                if row is None:
                    conflict("Both before and after evaluation runs are required")
                reports.append(json.loads(row[0]))
            before, after = reports
            for key in ("fixture_sha256", "fixture_version", "k", "N"):
                if before[key] != after[key]:
                    conflict("Before/after runs must use the same frozen benchmark and k")
            # Corpus-only changes must not silently change the embedding model/config too.
            if plan["operation"] != "retrieval_config":
                for key in ("embedding_model", "embedding_revision"):
                    if before["provenance"].get(key) != after["provenance"].get(key):
                        conflict("Embedding provenance differs; use an explicit retrieval-config proposal")
                if before["retrieval_config"] != after["retrieval_config"]:
                    conflict("Retrieval configuration differs")
            identifier = str(uuid.uuid4())
            stored = {**plan, "before_fingerprint": before["corpus_fingerprint"],
                      "after_fingerprint": after["corpus_fingerprint"],
                      "before_recall_at_k": before["recall_at_k"], "after_recall_at_k": after["recall_at_k"],
                      "fixture_sha256": before["fixture_sha256"], "k": before["k"]}
            db.execute("INSERT INTO corpus_changes(id,plan,created_at) VALUES (?,?,?)",
                       (identifier, dumps(stored), self.now()))
            self._change_event(db, identifier, "proposed", plan["actor"], stored)
        return identifier

    def _change_event(self, db, identifier, action, actor, data):
        db.execute("INSERT INTO corpus_change_events(change_id,action,actor,data,created_at) VALUES (?,?,?,?,?)",
                   (identifier, action, actor, dumps(data), self.now()))

    def start_corpus_change(self, identifier, operation, filename, file_sha256, fingerprint):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM corpus_changes WHERE id=?", (identifier,)).fetchone()
            if row is None:
                conflict("A reviewed change plan is required")
            plan = json.loads(row["plan"])
            if row["state"] != "proposed" or plan["operation"] != operation or plan["filename"] != filename or plan["file_sha256"] != file_sha256:
                conflict("Change plan does not match this operation, file, or content")
            if fingerprint != plan["before_fingerprint"]:
                conflict("Corpus changed since baseline evaluation; reevaluate before applying")
            verdict = db.execute("SELECT * FROM expert_verdicts WHERE id=?", (plan["verdict_id"],)).fetchone()
            latest = db.execute("SELECT MAX(id) FROM expert_verdicts WHERE response_id=?", (verdict["response_id"],)).fetchone()[0]
            if latest != verdict["id"]:
                conflict("The expert verdict changed; prepare a new change proposal")
            db.execute("UPDATE corpus_changes SET state='applying' WHERE id=?", (identifier,))
            self._change_event(db, identifier, "human_apply_started", plan["actor"], {})
        return plan

    def finish_corpus_change(self, identifier, fingerprint, failed=False):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT * FROM corpus_changes WHERE id=?", (identifier,)).fetchone()
            if row is None or row["state"] != "applying":
                conflict("Change was not started")
            plan = json.loads(row["plan"])
            if not failed and fingerprint != plan["after_fingerprint"]:
                conflict("Actual changed corpus differs from the evaluated candidate; roll back")
            state = "failed" if failed else "applied"
            db.execute("UPDATE corpus_changes SET state=? WHERE id=?", (state, identifier))
            self._change_event(db, identifier, state, plan["actor"], {"actual_fingerprint": fingerprint})

    def record_synthetic_baseline(self, before_run, after_run):
        # Only the explicit empty->synthetic bootstrap CLI may call this, never ratings/chat.
        identifier = str(uuid.uuid4())
        with closing(self.connect()) as db, db:
            plan = {"operation": "synthetic_baseline_setup", "before_run": before_run, "after_run": after_run}
            db.execute("INSERT INTO corpus_changes VALUES (?,?,'applied',?)", (identifier, dumps(plan), self.now()))
            self._change_event(db, identifier, "baseline_initialized", "local_operator", plan)
        return identifier
