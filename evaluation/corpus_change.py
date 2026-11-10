"""Explicit local candidate staging; never applies a proposal to the live app."""
import argparse
import hashlib
import json
from pathlib import Path

from backend.services.reviews import ReviewStore
from backend.services.ingestion import extract_text, chunk_text, build_chunk_ids
from backend.services.file_safety import upload_path
from backend.services.retrieval_trace import runtime_provenance, distance_metric
from evaluation.retrieval_holdout import CORPUS, evaluate_retrieval, open_vectorstore, load_frozen


def main():
    parser = argparse.ArgumentParser(description="Stop the backend and back up data before staging")
    parser.add_argument("--active-dir", required=True)
    parser.add_argument("--review-db", required=True)
    parser.add_argument("--bootstrap-synthetic", action="store_true")
    parser.add_argument("--candidate-dir")
    parser.add_argument("--upload")
    parser.add_argument("--delete")
    parser.add_argument("--verdict-id", type=int)
    parser.add_argument("--reason")
    parser.add_argument("--actor", default="Manufacturing Engineer")
    args = parser.parse_args()
    load_frozen()
    vector, embeddings = open_vectorstore(args.active_dir)
    store = ReviewStore(args.review_db)
    provenance = runtime_provenance(embeddings)
    before = evaluate_retrieval(vector, provenance)
    before_id = store.register_evaluation(before)
    if args.bootstrap_synthetic:
        if vector._collection.count() or args.upload or args.delete:
            parser.error("Synthetic bootstrap requires an empty collection and no other mutation")
        entries = json.loads(CORPUS.read_text())
        # Before+after evidence is recorded for this explicit initial setup, not a feedback-driven change.
        vector._collection.add(ids=[e["id"] for e in entries], documents=[e["text"] for e in entries],
                               metadatas=[e["metadata"] for e in entries],
                               embeddings=embeddings.embed_documents([e["text"] for e in entries]))
        after_id = store.register_evaluation(evaluate_retrieval(vector, provenance))
        print(json.dumps({"baseline_id": store.record_synthetic_baseline(before_id, after_id)}))
        return
    if not args.candidate_dir or bool(args.upload) == bool(args.delete) or not args.verdict_id or not args.reason:
        parser.error("Provide fresh --candidate-dir, one of --upload/--delete, --verdict-id and --reason")
    if Path(args.candidate_dir).exists():
        parser.error("Candidate directory must not exist; never overwrite a prior candidate")
    from langchain_community.vectorstores import Chroma
    metric = distance_metric(vector._collection)
    if metric not in {"l2", "cosine", "ip"}:
        parser.error("Resolve the active distance metric before staging a candidate")
    # Same in-memory embedding instance: never label a second, newly downloaded
    # model revision with the active model's provenance.
    candidate = Chroma(persist_directory=args.candidate_dir, embedding_function=embeddings,
                       collection_metadata={"hnsw:space": metric})
    data = vector._collection.get(include=["documents", "metadatas", "embeddings"])
    if data["ids"]:
        candidate._collection.add(ids=data["ids"], documents=data["documents"],
                                  metadatas=data["metadatas"], embeddings=data["embeddings"])
    if args.upload:
        source = Path(args.upload)
        filename = source.name
        upload_path(args.candidate_dir, filename)  # Same simple-filename rules as the HTTP route.
        content = source.read_bytes()
        if not content or len(content) > 20 * 1024 * 1024 or source.suffix.lower() not in {".md", ".pdf", ".docx"}:
            parser.error("Upload must match the app's bounded supported-file contract")
        kind = source.suffix.lower()[1:]
        chunks = chunk_text(extract_text(str(source), kind), str(source), filename, kind)
        candidate.add_documents(chunks, ids=build_chunk_ids(filename, chunks))
        file_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        operation = "upload"
    else:
        filename, file_hash, operation = args.delete, None, "delete"
        upload_path(args.candidate_dir, filename)
        ids = candidate._collection.get(where={"manual_name": filename}, include=[])["ids"]
        if not ids:
            parser.error("No matching source to delete in candidate")
        candidate.delete(ids=ids)
    after_id = store.register_evaluation(evaluate_retrieval(candidate, provenance))
    change_id = store.propose_corpus_change({"operation": operation, "filename": filename,
        "file_sha256": file_hash, "before_run": before_id, "after_run": after_id,
        "verdict_id": args.verdict_id, "reason": args.reason, "actor": args.actor})
    print(json.dumps({"change_id": change_id, "state": "proposed_only", "before_run": before_id, "after_run": after_id}))


if __name__ == "__main__":
    main()
