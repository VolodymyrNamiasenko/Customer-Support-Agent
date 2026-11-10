"""One score-aware Chroma query before DSPy; distances are not confidence."""
import hashlib
import json
import math
from datetime import UTC, datetime

import httpx
from langchain_core.documents import Document

from backend.config import MODEL_NAME, EMBEDDING_MODEL, OLLAMA_BASE_URL
from backend.services.retrieval import tag_sources


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def corpus_fingerprint(vectorstore):
    data = vectorstore._collection.get(include=["documents", "metadatas", "embeddings"])
    rows = []
    embeddings = data.get("embeddings")
    if embeddings is None:
        raise ValueError("Index embeddings unavailable for reproducible fingerprint")
    if len({len(data[key]) for key in ("ids", "documents", "metadatas", "embeddings")}) != 1:
        raise ValueError("Inconsistent Chroma snapshot")
    for identifier, text, meta, embedding in zip(data["ids"], data["documents"], data["metadatas"], embeddings):
        # Exclude volatile upload timestamps and machine-specific absolute paths.
        stable = {k: v for k, v in (meta or {}).items() if k not in ("upload_timestamp", "source")}
        rows.append({"id": identifier, "content": text, "metadata": stable,
                     "embedding": [float(value) for value in embedding]})
    return digest({"metric": distance_metric(vectorstore._collection),
                   "rows": sorted(rows, key=lambda row: row["id"])})


def distance_metric(collection):
    configuration = getattr(collection, "configuration", None)
    if isinstance(configuration, dict):
        for kind in ("hnsw", "spann"):
            if isinstance(configuration.get(kind), dict) and configuration[kind].get("space"):
                return configuration[kind]["space"]
    metadata = getattr(collection, "metadata", None)
    return metadata.get("hnsw:space", "unknown") if isinstance(metadata, dict) else "unknown"


def runtime_provenance(embeddings=None):
    result = {"chat_model": MODEL_NAME, "chat_model_digest": None,
              "embedding_model": EMBEDDING_MODEL, "embedding_revision": None,
              "observed_at": datetime.now(UTC).isoformat(), "unresolved": []}
    try:
        response = httpx.get(OLLAMA_BASE_URL.rstrip("/") + "/api/tags", timeout=2)
        response.raise_for_status()
        tag = MODEL_NAME.split("/", 1)[-1]
        result["chat_model_digest"] = next((m["digest"] for m in response.json().get("models", [])
                                             if m.get("name") == tag), None)
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    try:
        client = embeddings._client
        result["embedding_revision"] = client._first_module().auto_model.config._commit_hash
    except AttributeError:
        pass
    for field in ("chat_model_digest", "embedding_revision"):
        if not result[field]:
            result["unresolved"].append(field + ": runtime version not resolved")
    return result


def retrieve_with_trace(vectorstore, question, k, provenance):
    collection = vectorstore._collection
    count = collection.count()
    fingerprint = corpus_fingerprint(vectorstore)
    trace = {
        "schema_version": "1.0", "status": "completed", "k": k,
        "corpus_fingerprint": fingerprint, "distance_metric": distance_metric(collection),
        "score_kind": "distance", "lower_is_more_similar": True,
        "retrieval_method": "chroma_query", "provenance": provenance,
        "retrieved_at": datetime.now(UTC).isoformat(), "hits": [],
        "used_context_chunk_ids": [], "discarded_duplicates": [],
        "claim_level_usage": "not_observed",
    }
    if not count:
        return [], trace
    embedding = vectorstore._embedding_function.embed_query(question)
    raw = collection.query(query_embeddings=[embedding], n_results=min(k, count),
                           include=["documents", "metadatas", "distances"])
    if len({len(raw[key][0]) for key in ("ids", "documents", "metadatas", "distances")}) != 1:
        raise ValueError("Inconsistent Chroma query result")
    seen, selected = set(), []
    for rank, (identifier, text, meta, score) in enumerate(zip(
            raw["ids"][0], raw["documents"][0], raw["metadatas"][0], raw["distances"][0]), start=1):
        if not isinstance(identifier, str) or not isinstance(text, str) or not math.isfinite(score):
            raise ValueError("Invalid Chroma result")
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        trace["hits"].append({"chunk_id": identifier, "rank": rank, "score": float(score),
                              "score_kind": "distance", "metric": trace["distance_metric"],
                              "content_hash": content_hash})
        if content_hash in seen:
            trace["discarded_duplicates"].append({"chunk_id": identifier, "reason": "duplicate_content"})
            continue
        seen.add(content_hash)
        selected.append(Document(page_content=text, metadata={**(meta or {}), "chunk_id": identifier}))
        trace["used_context_chunk_ids"].append(identifier)
    return tag_sources(selected), trace
