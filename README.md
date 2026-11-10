# ERP Support Assistant · Pulse RAG Manager

A local document-management and question-answering prototype for ERP/MES support. It demonstrates how solution documentation can support an answer while preserving source visibility and restrictions for integration-owned data.

Upload manuals and integration blueprints, inspect indexed chunks, and ask questions against retrieved evidence. The public repository contains application code and synthetic examples, not client manuals, pilot feedback or an independently validated performance benchmark.

## Workflow and review boundary

1. An operator uploads approved Markdown, PDF or DOCX documentation.
2. The backend chunks text, embeds it and stores it in a local Chroma index.
3. Chroma retrieves snippets before DSPy; DSPy generates through Ollama using only the supplied tagged context.
4. A heuristic response check looks for integration/read-only signals and may replace an unsafe answer with a restriction notice.
5. The interface shows a draft answer, retrieved source names and rule-check status. Every answer is saved in the Reviews queue.
6. A reviewer records release approval/rejection; customer satisfaction (1–5) and expert correctness are recorded separately. The release endpoint and Copy approved answer action require approval. Missing evidence, failed checks or an explicit negative SME verdict prevent approval.

Source names identify **retrieved documents**, not proof that every answer claim is supported. The review workflow records versioned decisions and history in a local SQLite database; reviewer names are self-reported in this single-user application, not authenticated identities. A passing rule check is not a factual-accuracy score. Draft answers remain visible for review. Empty retrieval abstains; weak or irrelevant nonempty retrieval can still produce a bad answer.

## Review and feedback

Open **Reviews** after asking a question. Inspect sources, trace and history. Save an anonymous customer-satisfaction rating, or a separate Manufacturing Engineer correctness verdict with evidence. Ratings never imply correctness; release approval also does not supply an expert label. The expert queue includes low ratings, a stable 10% inclusion-probability sample of high ratings and all flagged guard-relevant high ratings. Concurrent/stale changes return a conflict.

See **[pilot instrumentation and safe operating instructions](docs/PILOT.md)** for approved policy, additive migration, endpoints, frozen retrieval held-out, human-controlled corpus changes and private schema-versioned export. Pilot uploads/deletes require an SME-linked evaluated change ID; ratings never modify the corpus or search. Only synthetic examples/fixtures belong in this repository.

`REVIEW_DB_PATH` optionally selects a private local SQLite file; default: `data/reviews.sqlite3`. It stores questions, answers, decisions, feedback and event history. Keep this directory private and out of Git. The app does not automatically send an approved answer to ERP/MES or enforce review outside its release endpoint.

API: `GET /api/reviews`, `GET /api/reviews/metrics`, `GET /api/reviews/{id}`, `POST /api/reviews/{id}/decision`, `POST /api/reviews/{id}/rating`, `GET /api/reviews/{id}/release`. Decision/rating requests require the current `version`, `actor` and decision/rating. See [workflow checks](docs/ADVANCED_WORKFLOWS.md).

## What is implemented

- FastAPI backend and React/Vite/Tailwind interface.
- Markdown, PDF and DOCX ingestion with structural and recursive chunking.
- Chroma retrieval using all-mpnet-base-v2 embeddings.
- DSPy generation through a local Ollama model.
- Source attribution and a heuristic guard for SAP-integrated/read-only entities.
- Bounded uploads, safe filenames, duplicate detection and atomic registry updates.

A rule-based guard reduces some unsafe procedural answers; it does **not** prove factual accuracy or prevent every prompt injection.

## Quick start

Requires Python 3.11+, Node.js 20.19+ (or 22.12+), Ollama and enough memory for the selected models. The first embedding load may download model weights.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
# Start Ollama separately if it is not already running.
ollama pull llama3.2:3b
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. API documentation: http://localhost:8000/docs.
Set `VITE_API_BASE_URL` before building if the backend address differs.

For a non-client smoke test, upload [the synthetic support guide](examples/synthetic_support_guide.md). Ask which system owns Demo Orders, inspect the source label and compare the answer with the guide. Model wording is nondeterministic; this is a walkthrough, not pilot evidence. See [portfolio evidence and acceptance checks](docs/PORTFOLIO.md).

The backend defaults are in `backend/config.py`: `ollama_chat/llama3.2:3b`, Ollama at `http://localhost:11434`, and `sentence-transformers/all-mpnet-base-v2` embeddings. An embedding download and a running Ollama service are required for the real workflow. No proprietary ERP/MES connection is implemented; the assistant operates over supplied documents.

## Checks

```bash
python -m unittest discover -s tests -v
cd frontend
npm run build
```

Tests use temporary files and a fake vector store; they do not download models or call Ollama.

## Data and operating limits

Uploads, the document registry and vector index must be backed up together. Run **one backend worker**: the JSON registry lock is process-local and there is no cross-store transaction. Do not expose this app directly to the internet: user authentication, authorization, rate limits and durable multi-process storage are not implemented.

Do not commit private documents, feedback, indexes, registry metadata, prompt-optimization artifacts or credentials. The local model does not imply that every supporting library is offline: prepare/download dependencies and models separately if network isolation is required.

An empty retrieval result produces an explicit insufficient-evidence answer. Retrieved text is treated as untrusted, but prompt instructions are not a complete security boundary. OCR for scanned PDFs is not included. No accuracy, latency or production-readiness guarantee is claimed.

See [evaluation guidance](docs/EVALUATION.md) for the CS230-informed validation workflow.
