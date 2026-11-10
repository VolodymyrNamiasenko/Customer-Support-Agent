"""Frozen retrieval evaluation, independent of the six development guard cases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from backend.services.retrieval_trace import retrieve_with_trace, corpus_fingerprint, runtime_provenance

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "heldout/retrieval_v1.json"
CORPUS = ROOT / "heldout/corpus_v1.json"
FROZEN_V1 = {
    "retrieval_v1.json": "19eb8957969b78a602bc1687dc74f60ce47a3826b689cc1d42c2568518c70819",
    "corpus_v1.json": "e180a8cbafc0ac127ae9c5e22c467ffd5c181c3ccc884a2c46b114496194a36b",
}


def normalize(value):
    return re.sub(r"\W+", " ", value.casefold()).strip()


def load_frozen():
    manifest = json.loads((ROOT / "heldout/manifest.json").read_text())
    if manifest["sha256"] != FROZEN_V1 or manifest["version"] != "synthetic-retrieval-heldout-v1":
        raise ValueError("V1 manifest changed without a new independently reviewed benchmark")
    for path in (FIXTURE, CORPUS):
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"][path.name]:
            raise ValueError("Frozen held-out changed; create a reviewed new benchmark version instead")
    fixture = json.loads(FIXTURE.read_text())
    if fixture["version"] != manifest["version"] or fixture["split"] != "heldout" or fixture["k"] != 3:
        raise ValueError("Frozen fixture configuration changed")
    corpus = json.loads(CORPUS.read_text())
    corpus_ids = {row["id"] for row in corpus}
    if len(corpus_ids) != len(corpus):
        raise ValueError("Duplicate frozen corpus IDs")
    dev = json.loads((ROOT / "cases.json").read_text())
    texts = {normalize(c.get("question", c.get("context", ""))) for c in dev}
    ids, questions = set(), set()
    for case in fixture["cases"]:
        question = normalize(case["question"])
        if case["id"] in ids or question in questions or question in texts:
            raise ValueError("Duplicate/leaked evaluation case")
        ids.add(case["id"])
        questions.add(question)
        if not case["relevant_ids"] or len(set(case["relevant_ids"])) != len(case["relevant_ids"]):
            raise ValueError("Gold relevant IDs must be nonempty and unique")
        if not set(case["relevant_ids"]).issubset(corpus_ids):
            raise ValueError("Gold label missing from the frozen synthetic corpus")
    return fixture, manifest


def recall_at_k(retrieved, relevant, k):
    if not relevant or k < 1:
        raise ValueError("Recall needs nonempty gold and positive k")
    return len(set(retrieved[:k]) & set(relevant)) / len(set(relevant))


def evaluate_retrieval(vectorstore, provenance):
    fixture, manifest = load_frozen()
    results = []
    for case in fixture["cases"]:
        _, trace = retrieve_with_trace(vectorstore, case["question"], fixture["k"], provenance)
        ids = [hit["chunk_id"] for hit in trace["hits"]]
        results.append({"case_id": case["id"], "retrieved_ids": ids,
                        "relevant_ids": case["relevant_ids"],
                        "recall_at_k": recall_at_k(ids, case["relevant_ids"], fixture["k"])})
    return {"schema_version": "1.0", "mode": "chroma_retrieval", "fixture_version": fixture["version"],
            "fixture_sha256": manifest["sha256"][FIXTURE.name], "k": fixture["k"], "N": len(results),
            "recall_at_k": sum(r["recall_at_k"] for r in results) / len(results), "results": results,
            "corpus_fingerprint": corpus_fingerprint(vectorstore), "provenance": provenance,
            "retrieval_config": {"method": "chroma_query", "metric": trace["distance_metric"]},
            "scope": fixture["scope"]}


def open_vectorstore(path):
    from langchain_community.vectorstores import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings
    from backend.config import EMBEDDING_MODEL
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return Chroma(persist_directory=str(path), embedding_function=embeddings), embeddings


def private_json(path, value):
    # Refuse overwrite, including a symlink. Do not put private exports in the repository.
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-db")
    args = parser.parse_args()
    load_frozen()
    vector, embeddings = open_vectorstore(args.collection_path)
    report = evaluate_retrieval(vector, runtime_provenance(embeddings))
    if args.review_db:
        from backend.services.reviews import ReviewStore
        report_id = ReviewStore(args.review_db).register_evaluation(report)
        report = {**report, "evaluation_run_id": report_id}
    private_json(args.output, report)
    print(json.dumps({"recall_at_k": report["recall_at_k"], "N": report["N"], "output": args.output}))


if __name__ == "__main__":
    main()
