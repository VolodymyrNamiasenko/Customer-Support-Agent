"""Persistent, versioned human decisions for the trusted-local support app."""

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from backend.services.pilot import PilotReviewMixin
from backend.services.corpus_governance import CorpusGovernanceMixin


class ReviewConflict(ValueError):
    pass


class ReviewStore(PilotReviewMixin, CorpusGovernanceMixin):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS responses (
                    id TEXT PRIMARY KEY, question TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', version INTEGER NOT NULL DEFAULT 1,
                    reviewer TEXT, review_note TEXT, rating INTEGER, feedback TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, response_id TEXT NOT NULL,
                    action TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
                    version INTEGER NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(response_id) REFERENCES responses(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS review_status ON responses(status, created_at);
            """)
        self.path.chmod(0o600)
        self.migrate_pilot()

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def now():
        return datetime.now(UTC).isoformat()

    @staticmethod
    def decode(row):
        result = dict(row)
        result["response"] = json.loads(result.pop("payload"))
        return result

    def create(self, question, payload):
        identifier, now = str(uuid.uuid4()), self.now()
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO responses(id, question, payload, created_at, updated_at) VALUES (?,?,?,?,?)",
                (
                    identifier,
                    question,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO review_events(response_id, action, actor, note, version, created_at) VALUES (?,?,?,?,?,?)",
                (identifier, "generated", "system", "", 1, now),
            )
        return self.get(identifier)

    def get(self, identifier):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT * FROM responses WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            result = self.decode(row)
            result["events"] = [
                dict(r)
                for r in db.execute(
                    "SELECT id, action, actor, note, version, created_at, data FROM review_events WHERE response_id=? ORDER BY id",
                    (identifier,),
                )
            ]
            for event in result["events"]:
                event["data"] = json.loads(event["data"])
                if event["action"].startswith("rated:"):
                    event["actor"] = "anonymous_customer"
            trace = db.execute("SELECT trace FROM retrieval_traces WHERE response_id=?", (identifier,)).fetchone()
            result["retrieval_trace"] = json.loads(trace[0]) if trace else None
            return result

    def list(self, status=None, limit=25, offset=0):
        where, params = ("WHERE status=?", [status]) if status else ("", [])
        with closing(self.connect()) as db:
            total = db.execute(
                f"SELECT COUNT(*) FROM responses {where}", params
            ).fetchone()[0]
            rows = db.execute(
                f"SELECT * FROM responses {where} ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
            return {
                "items": [self.decode(r) for r in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def update(self, identifier, version, actor, note, *, decision=None, rating=None):
        if decision is not None and rating is not None:
            raise ValueError("Decision and satisfaction rating are separate actions")
        if rating is not None:
            return self.rate_anonymously(identifier, version, rating, note)
        if decision not in (None, "approved", "rejected"):
            raise ValueError("Invalid review decision")
        if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
            raise ValueError("Rating must be an integer from 1 to 5")
        if not actor.strip():
            raise ValueError("Reviewer name is required")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM responses WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            if row["version"] != version:
                raise ReviewConflict(
                    "This response changed. Refresh it before submitting."
                )
            payload = json.loads(row["payload"])
            if decision == "approved" and (
                row["generation_state"] not in ("legacy", "completed") or
                row["correctness"] in ("partially_correct", "incorrect") or
                not payload.get("sources") or not payload.get(
                    "hallucination_guard", {}
                ).get("is_valid")
            ):
                raise ReviewConflict(
                    "A response with missing evidence or a failed rule check cannot be approved."
                )
            now, new_version = self.now(), version + 1
            if decision:
                db.execute(
                    "UPDATE responses SET status=?, reviewer=?, review_note=?, version=?, updated_at=? WHERE id=?",
                    (decision, actor.strip(), note, new_version, now, identifier),
                )
                action = decision
            elif rating is not None:
                db.execute(
                    "UPDATE responses SET rating=?, feedback=?, version=?, updated_at=? WHERE id=?",
                    (rating, note, new_version, now, identifier),
                )
                action = f"rated:{rating}"
            else:
                raise ValueError("A decision or rating is required")
            db.execute(
                "INSERT INTO review_events(response_id, action, actor, note, version, created_at) VALUES (?,?,?,?,?,?)",
                (identifier, action, actor.strip(), note, new_version, now),
            )
        return self.get(identifier)

    def release(self, identifier):
        record = self.get(identifier)
        if record["status"] != "approved":
            raise ReviewConflict(
                "Human approval is required before releasing this answer."
            )
        approval = next(
            e for e in reversed(record["events"]) if e["action"] == "approved"
        )
        return {
            "id": identifier,
            "answer": record["response"]["answer"],
            "sources": record["response"]["sources"],
            "reviewer": record["reviewer"],
            "reviewed_at": approval["created_at"],
            "version": record["version"],
        }

    def metrics(self):
        with closing(self.connect()) as db:
            statuses = {
                r["status"]: r["n"]
                for r in db.execute(
                    "SELECT status, COUNT(*) AS n FROM responses GROUP BY status"
                )
            }
            row = db.execute(
                "SELECT COUNT(rating) AS rated, AVG(rating) AS mean FROM responses"
            ).fetchone()
        return {
            "total": sum(statuses.values()),
            "pending": statuses.get("pending", 0),
            "approved": statuses.get("approved", 0),
            "rejected": statuses.get("rejected", 0),
            "rated_responses": row["rated"],
            "mean_rating": row["mean"],
        }
