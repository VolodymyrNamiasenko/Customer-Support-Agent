"""Contract fakes only, never reported as model/retrieval quality evidence."""
from backend.services.pilot import dumps

PROVENANCE = {"chat_model": "synthetic/chat", "chat_model_digest": "synthetic-digest",
              "embedding_model": "synthetic/embedding", "embedding_revision": "synthetic-revision"}


def configure_vector(vector):
    vector.similarity_search.return_value = []  # Old tests set documents here; not called by the app.
    vector._collection.configuration = {"hnsw": {"space": "cosine"}}
    vector._collection.count.return_value = 1
    vector._embedding_function.embed_query.return_value = [1.0, 0.0]
    def data():
        docs = vector.similarity_search.return_value
        return {"ids": [f"synthetic-{i}" for i in range(len(docs))],
                "documents": [d.page_content for d in docs], "metadatas": [d.metadata for d in docs],
                "embeddings": [[1.0, 0.0] for _ in docs]}
    vector._collection.get.side_effect = lambda **kwargs: data()
    def query(**kwargs):
        raw = data()
        return {key: [value] for key, value in {**raw, "distances": [0.1] * len(raw["ids"])}.items()}
    vector._collection.query.side_effect = query


def trace(hits=None):
    return {"schema_version": "1.0", "status": "completed", "k": 5,
            "provenance": PROVENANCE, "hits": hits or [], "used_context_chunk_ids": [],
            "claim_level_usage": "not_observed"}
