import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from backend.services import document_store
from backend.services.file_safety import upload_path
from backend.services.retrieval import deduplicate_docs, tag_sources
from backend.routers import documents, rag, chat
from backend.hallucination_guard import validate_response
from backend.services.reviews import ReviewStore


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = patch.object(document_store, "DOCUMENT_REGISTRY", str(self.root / "registry.json"))
        self.registry.start()
        self.addCleanup(self.registry.stop)
        self.uploads = patch.object(documents, "UPLOAD_DIR", str(self.root / "uploads"))
        self.uploads.start()
        self.addCleanup(self.uploads.stop)
        self.vector = Mock()
        self.vector._collection.count.return_value = 1
        app = FastAPI()
        app.state.vectorstore = self.vector
        app.state.review_store = ReviewStore(self.root / 'reviews.sqlite3')
        app.state.write_lock = Lock()
        app.include_router(documents.router, prefix="/api/documents")
        app.include_router(rag.router, prefix="/api/rag")
        app.include_router(chat.router, prefix="/api")
        self.client = TestClient(app)

    def test_invalid_names_and_symlinks(self):
        for name in (None, "../evil.md", "/tmp/evil.md", "..\\evil.md", ".", "bad\x00.md"):
            with self.assertRaises(ValueError):
                upload_path(self.temp.name, name)
        (self.root / "link.md").symlink_to(self.root / "outside")
        with self.assertRaises(ValueError):
            upload_path(self.temp.name, "link.md")

    def test_registry_concurrent_updates(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: document_store.upsert_document(str(i), {"index": i}), range(30)))
        self.assertEqual(len(document_store.load_registry().documents), 30)

    def test_registry_creates_parent_directory(self):
        with patch.object(document_store, "DOCUMENT_REGISTRY", str(self.root / "nested/registry.json")):
            document_store.upsert_document("guide.md", {"chunk_count": 1})
            self.assertIn("guide.md", document_store.load_registry().documents)

    def test_upload_duplicate_and_delete(self):
        result = self.client.post("/api/documents/upload", files={"file": ("guide.md", b"# Title\nReal evidence", "text/markdown")})
        self.assertEqual(result.status_code, 201, result.text)
        duplicate = self.client.post("/api/documents/upload", files={"file": ("guide.md", b"different", "text/markdown")})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual((self.root / "uploads/guide.md").read_bytes(), b"# Title\nReal evidence")
        self.assertEqual(self.client.delete("/api/documents/guide.md").status_code, 200)
        self.assertFalse((self.root / "uploads/guide.md").exists())

    def test_reject_empty_and_traversal(self):
        for name, content in (("empty.md", b""), ("../evil.md", b"bad")):
            self.assertEqual(self.client.post("/api/documents/upload", files={"file": (name, content)}).status_code, 400)

    def test_failed_index_rolls_back(self):
        self.vector.add_documents.side_effect = RuntimeError("index unavailable")
        with self.assertRaises(RuntimeError):
            self.client.post("/api/documents/upload", files={"file": ("failed.md", b"Some text")})
        self.assertFalse((self.root / "uploads/failed.md").exists())
        self.assertEqual(document_store.load_registry().documents, {})
        self.vector.delete.assert_called_once()

    def test_chunk_include_and_total(self):
        def get(**kwargs):
            self.assertNotIn("ids", kwargs["include"])
            if not kwargs["include"]:
                return {"ids": ["1", "2", "3"]}
            return {"ids": ["1"], "documents": ["text"], "metadatas": [{}]}
        self.vector._collection.get.side_effect = get
        result = self.client.get("/api/rag/chunks?limit=1").json()
        self.assertEqual(result["total"], 3)

    def test_no_evidence_does_not_call_llm(self):
        self.vector.similarity_search.return_value = []
        with patch.object(chat, "run_inference") as infer:
            result = self.client.post("/api/chat", json={"question": "How?"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["sources"], [])
        infer.assert_not_called()

    def test_answer_exposes_retrieved_sources_and_guard(self):
        guide = Path(__file__).resolve().parents[1] / "examples/synthetic_support_guide.md"
        self.vector.similarity_search.return_value = [
            Document(page_content=guide.read_text(), metadata={"source": str(guide)})
        ]
        answer = "Demo Orders cannot be manually created; review the source system."
        check = validate_response(guide.read_text(), answer)
        with patch.object(chat, "run_inference", return_value=(SimpleNamespace(reasoning=""), answer, check)) as infer:
            response = self.client.post("/api/chat", json={"question": "Which system owns Demo Orders?"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sources"], [guide.name])
        self.assertEqual(body["context_snippets"][0]["source"], str(guide))
        self.assertEqual(body["answer"], answer)
        self.assertTrue(body["hallucination_guard"]["entity_is_integrated"])
        self.assertIn("untrusted document text", infer.call_args.kwargs["context_text"])

    def test_synthetic_integration_rule_blocks_unqualified_creation_advice(self):
        context = "Demo Orders are imported from SAP and are read-only."
        self.assertFalse(validate_response(context, "Click New to create an order.").is_valid)
        self.assertTrue(validate_response(context, "Orders cannot be manually created.").is_valid)

    def test_full_content_dedup_and_no_mutation(self):
        a = Document(page_content="x" * 200 + "first", metadata={"source": "manual.md"})
        b = Document(page_content="x" * 200 + "second")
        self.assertEqual(len(deduplicate_docs([a, b])), 2)
        tagged = tag_sources([a])
        self.assertTrue(tagged[0].page_content.startswith("[MANUAL]"))
        self.assertFalse(a.page_content.startswith("[MANUAL]"))


if __name__ == "__main__":
    unittest.main()
