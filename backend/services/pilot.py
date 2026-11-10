"""Additive pilot instrumentation for ReviewStore. No customer identity mapping."""
import hashlib
import json
import secrets
import uuid
from contextlib import closing

TAXONOMY = (
    "bad_label", "missing_source", "wrong_retrieval", "source_conflict",
    "unsupported_claim", "unsupported_action", "hallucinated_step",
    "malformed_input", "timeout", "duplicate_import", "subgroup_mismatch",
)
CORRECTNESS = ("correct", "partially_correct", "incorrect")
SME_ROLE = "Manufacturing Engineer"
POLICY_VERSION = "pilot-v1"
SCHEMA_VERSION = "1.0"


def conflict(message):
    from backend.services.reviews import ReviewConflict
    raise ReviewConflict(message)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def metrics_for(records):
    # Do not silently turn historical reviewer ratings into customer-pilot evidence.
    pilot = [r for r in records if r["cohort"] == "pilot-v1"]
    rated = [r["rating"] for r in pilot if r["rating"] is not None]
    judged = [r for r in pilot if r["correctness"] is not None]
    counts = {key: sum(r["correctness"] == key for r in judged) for key in CORRECTNESS}
    return {
        "cohort": "pilot-v1", "N_responses": len(pilot),
        "satisfaction": {"N": len(rated), "mean_rating": sum(rated) / len(rated) if rated else None},
        "expert_correctness": {
            "N_reviewed": len(judged), "counts": counts,
            "correct_fraction": counts["correct"] / len(judged) if judged else None,
            "coverage": len(judged) / len(pilot) if pilot else None,
            "scope": "Selected expert sample; not an unbiased whole-pilot accuracy estimate",
        },
        "legacy_or_nonpilot_responses": len(records) - len(pilot),
    }


class PilotReviewMixin:
    def migrate_pilot(self):
        with closing(self.connect()) as db, db:
            additions = {
                "generation_state": "TEXT NOT NULL DEFAULT 'legacy'",
                "cohort": "TEXT NOT NULL DEFAULT 'legacy_unknown'",
                "correctness": "TEXT", "error_bucket": "TEXT",
                "expert_role": "TEXT", "expert_note": "TEXT",
            }
            existing = {r["name"] for r in db.execute("PRAGMA table_info(responses)")}
            for name, definition in additions.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE responses ADD COLUMN {name} {definition}")
            if "data" not in {r["name"] for r in db.execute("PRAGMA table_info(review_events)")}:
                db.execute("ALTER TABLE review_events ADD COLUMN data TEXT NOT NULL DEFAULT '{}'")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pilot_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS retrieval_traces (
                    response_id TEXT PRIMARY KEY REFERENCES responses(id),
                    trace TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS expert_verdicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    response_id TEXT NOT NULL REFERENCES responses(id),
                    response_version INTEGER NOT NULL, correctness TEXT NOT NULL,
                    error_bucket TEXT, rationale TEXT NOT NULL, evidence TEXT NOT NULL,
                    actor TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queue_selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    response_id TEXT NOT NULL REFERENCES responses(id),
                    reason TEXT NOT NULL, policy_version TEXT NOT NULL,
                    draw REAL NOT NULL, rating_version INTEGER NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(response_id, reason, policy_version)
                );
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    id TEXT PRIMARY KEY, report TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS corpus_changes (
                    id TEXT PRIMARY KEY, plan TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'proposed', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS corpus_change_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_id TEXT NOT NULL REFERENCES corpus_changes(id),
                    action TEXT NOT NULL, actor TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            policy = {
                "version": POLICY_VERSION, "high_sample_probability": 0.10,
                "low_ratings": [1, 2], "high_ratings": [4, 5], "sme_role": SME_ROLE,
                "sampling": "Stable Bernoulli per response, not an exact 10% quota",
                "seed": secrets.token_hex(32),
                "rating_actor": "anonymous_customer", "identity_mapping": False,
                "authorization": "Operator authorized storage and anonymized raters on 2026-11-10",
                "participant_consent_verified_by_app": False,
            }
            db.execute("INSERT OR IGNORE INTO pilot_settings VALUES ('policy', ?)", (dumps(policy),))
            for table in ("review_events", "retrieval_traces", "expert_verdicts", "queue_selections",
                          "evaluation_runs", "corpus_change_events"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} "
                               f"BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only audit'); END")

    def policy(self, db=None):
        if db is not None:
            return json.loads(db.execute("SELECT value FROM pilot_settings WHERE key='policy'").fetchone()[0])
        with closing(self.connect()) as conn:
            return self.policy(conn)

    def _event(self, db, identifier, action, version, actor="system", note="", data=None):
        db.execute("INSERT INTO review_events(response_id,action,actor,note,version,created_at,data) "
                   "VALUES (?,?,?,?,?,?,?)", (identifier, action, actor, note, version, self.now(), dumps(data or {})))

    @staticmethod
    def _expected(db, identifier, version):
        row = db.execute("SELECT * FROM responses WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        if row["version"] != version:
            conflict("This response changed. Refresh before submitting.")
        return row

    def begin_attempt(self, question):
        identifier, now = str(uuid.uuid4()), self.now()
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO responses(id,question,payload,created_at,updated_at,generation_state,cohort) "
                       "VALUES (?,?,?,?,?,'retrieving','pilot-v1')",
                       (identifier, question, dumps({}), now, now))
            self._event(db, identifier, "attempt_started", 1)
        return self.get(identifier)

    def save_trace(self, identifier, version, trace):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._expected(db, identifier, version)
            if row["generation_state"] != "retrieving":
                conflict("Retrieval trace can only be recorded once.")
            db.execute("INSERT INTO retrieval_traces VALUES (?,?,?)", (identifier, dumps(trace), self.now()))
            db.execute("UPDATE responses SET generation_state='generating',version=version+1,updated_at=? WHERE id=?",
                       (self.now(), identifier))
            self._event(db, identifier, "retrieval_recorded", version + 1)
        return self.get(identifier)

    def finish_attempt(self, identifier, version, payload, *, failed=False):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._expected(db, identifier, version)
            if row["generation_state"] not in ("retrieving", "generating"):
                conflict("Attempt is already finalized.")
            state = "failed" if failed else "completed"
            db.execute("UPDATE responses SET payload=?,generation_state=?,version=version+1,updated_at=? WHERE id=?",
                       (dumps(payload), state, self.now(), identifier))
            self._event(db, identifier, "generation_failed" if failed else "generated", version + 1,
                        data={"guard_replacement": payload.get("guard_replacement", False),
                              "claim_level_chunk_usage": "not_observed"})
        return self.get(identifier)

    def rate_anonymously(self, identifier, version, rating, note):
        if type(rating) is not int or not 1 <= rating <= 5:
            raise ValueError("Rating must be an integer from 1 to 5")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._expected(db, identifier, version)
            if row["generation_state"] not in ("completed", "legacy"):
                conflict("Only completed responses can be rated.")
            db.execute("UPDATE responses SET rating=?,feedback=?,version=version+1,updated_at=? WHERE id=?",
                       (rating, note, self.now(), identifier))
            self._event(db, identifier, f"rated:{rating}", version + 1, actor="anonymous_customer", note=note,
                        data={"measure": "satisfaction", "identity_retained": False})
            self._select_queue(db, row, rating, version + 1)
        return self.get(identifier)

    def _select_queue(self, db, row, rating, version):
        policy = self.policy(db)
        draw = int(hashlib.sha256((policy["seed"] + row["id"]).encode()).hexdigest(), 16) / 2**256
        payload = json.loads(row["payload"])
        guard = payload.get("hallucination_guard", {})
        relevant = bool(payload.get("guard_relevant") or guard.get("entity_is_integrated") or guard.get("has_non_creation_signal"))
        reasons = []
        if rating in policy["low_ratings"]:
            reasons.append("low_satisfaction")
        if rating in policy["high_ratings"]:
            if draw < policy["high_sample_probability"]:
                reasons.append("random_high_satisfaction")
            if guard.get("is_valid") and relevant:
                reasons.append("guard_relevant_high_satisfaction")
            if guard.get("is_valid") and ("entity_is_integrated" not in guard or
                                          "has_non_creation_signal" not in guard):
                reasons.append("unknown_ownership_high_satisfaction")
        for reason in reasons:
            inserted = db.execute("INSERT OR IGNORE INTO queue_selections "
                                  "(response_id,reason,policy_version,draw,rating_version,created_at) VALUES (?,?,?,?,?,?)",
                                  (row["id"], reason, policy["version"], draw, version, self.now())).rowcount
            if inserted:
                self._event(db, row["id"], "expert_queue_selected", version,
                            data={"reason": reason, "policy_version": policy["version"], "draw": draw})

    def expert_verdict(self, identifier, version, correctness, error_bucket, rationale, evidence):
        if correctness not in CORRECTNESS:
            raise ValueError("Invalid correctness")
        if ((correctness == "correct" and error_bucket is not None) or
                (correctness != "correct" and error_bucket not in TAXONOMY)):
            raise ValueError("Use no bucket for correct; otherwise choose a taxonomy bucket")
        if not rationale.strip() or not evidence or any(not e.strip() for e in evidence):
            raise ValueError("Expert rationale and evidence references are required")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._expected(db, identifier, version)
            if row["generation_state"] not in ("completed", "legacy"):
                conflict("A failed or unfinished attempt is not an answer to judge.")
            verdict_id = db.execute("INSERT INTO expert_verdicts "
                "(response_id,response_version,correctness,error_bucket,rationale,evidence,actor,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (identifier, version + 1, correctness, error_bucket,
                                           rationale, dumps(evidence), SME_ROLE, self.now())).lastrowid
            db.execute("UPDATE responses SET correctness=?,error_bucket=?,expert_role=?,expert_note=?,"
                       "version=version+1,updated_at=? WHERE id=?",
                       (correctness, error_bucket, SME_ROLE, rationale, self.now(), identifier))
            # A negative expert verdict must invalidate an earlier release approval.
            if correctness != "correct":
                db.execute("UPDATE responses SET status='rejected' WHERE id=?", (identifier,))
            self._event(db, identifier, "expert_verdict", version + 1, actor=SME_ROLE, note=rationale,
                        data={"verdict_id": verdict_id, "correctness": correctness,
                              "error_bucket": error_bucket, "taxonomy_version": "1", "evidence": evidence,
                              "identity_assurance": "self_reported_role"})
        return self.get(identifier)

    def expert_queue(self, limit=25, offset=0, include_reviewed=False):
        with closing(self.connect()) as db:
            where = "" if include_reviewed else "AND r.correctness IS NULL"
            rows = list(db.execute("SELECT r.* FROM responses r WHERE EXISTS "
                                   "(SELECT 1 FROM queue_selections s WHERE s.response_id=r.id) "
                                   f"{where} ORDER BY r.created_at,r.id"))
            items = []
            for row in rows[offset:offset + limit]:
                item = self.decode(row)
                item["selection_reasons"] = [r[0] for r in db.execute(
                    "SELECT reason FROM queue_selections WHERE response_id=? ORDER BY id", (row["id"],))]
                items.append(item)
            return {"items": items, "total": len(rows), "limit": limit, "offset": offset,
                    "policy": self.policy(db)}

    def pilot_metrics(self):
        with closing(self.connect()) as db:
            return metrics_for([dict(r) for r in db.execute("SELECT * FROM responses")])

    def export_snapshot(self):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            records = [self.decode(r) for r in db.execute("SELECT * FROM responses ORDER BY created_at,id")]
            events = [dict(r) for r in db.execute("SELECT * FROM review_events ORDER BY id")]
            for event in events:
                if event["action"].startswith("rated:"):
                    event["actor"] = "anonymous_customer"  # Also sanitize historical exported rating actors.
                event["data"] = json.loads(event["data"])
            traces = [{"response_id": r["response_id"], "created_at": r["created_at"],
                       "trace": json.loads(r["trace"])} for r in db.execute("SELECT * FROM retrieval_traces ORDER BY response_id")]
            evaluations = [{"id": r["id"], "created_at": r["created_at"], "report": json.loads(r["report"])}
                           for r in db.execute("SELECT * FROM evaluation_runs ORDER BY id")]
            changes = [{**dict(r), "plan": json.loads(r["plan"])} for r in db.execute("SELECT * FROM corpus_changes ORDER BY id")]
            change_events = [{**dict(r), "data": json.loads(r["data"])} for r in db.execute("SELECT * FROM corpus_change_events ORDER BY id")]
            selections = [dict(r) for r in db.execute("SELECT * FROM queue_selections ORDER BY id")]
            verdicts = [{**dict(r), "evidence": json.loads(r["evidence"])}
                        for r in db.execute("SELECT * FROM expert_verdicts ORDER BY id")]
            return {"schema_version": SCHEMA_VERSION, "exported_at": self.now(), "taxonomy_version": "1",
                    "policy": self.policy(db), "records": records, "review_events": events,
                    "retrieval_traces": traces, "expert_verdicts": verdicts, "queue_selections": selections,
                    "evaluation_runs": evaluations, "corpus_changes": changes, "corpus_change_events": change_events,
                    "metrics": metrics_for(records), "privacy": {
                        "rating_identity": "anonymous_customer; no identifier mapping",
                        "free_text": "Questions, answers and comments are NOT automatically de-identified",
                        "legacy_database": "Original append-only legacy actors remain in private storage; exported rating actors are anonymized",
                    }}
