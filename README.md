# ERP Support Assistant · Pulse RAG Manager

A local document-management and question-answering prototype for ERP/MES support. It demonstrates how solution documentation can support an answer while preserving source visibility and restrictions for integration-owned data.

Upload manuals and integration blueprints, inspect indexed chunks, and ask questions against retrieved evidence. The public repository contains application code and synthetic examples, not client manuals, pilot feedback or an independently validated performance benchmark.

## Workflow and review boundary

1. An operator uploads approved Markdown, PDF or DOCX documentation.
2. The backend chunks text, embeds it and stores it in a local Chroma index.
3. A question retrieves snippets; DSPy passes tagged evidence to Ollama.
4. A heuristic response check looks for integration/read-only signals and may replace an unsafe answer with a restriction notice.
5. The interface shows the answer, retrieved source names and guard status. A person checks the supporting material before applying advice.

Source names identify **retrieved documents**, not proof that every answer claim is supported. Human review is an operating practice, not a built-in approval workflow. A passing guard is not a factual-accuracy score. Empty retrieval abstains; weak or irrelevant nonempty retrieval can still produce a bad answer.

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
