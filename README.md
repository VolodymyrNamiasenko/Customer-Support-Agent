# Pulse RAG Manager

A local document-management and question-answering application for Pulse ERP support. Upload manuals and integration blueprints, inspect indexed chunks, and ask questions against the retrieved evidence.

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

## Checks

```bash
python -m unittest discover -s tests -v
cd frontend
npm run build
```

Tests use temporary files and a fake vector store; they do not download models or call Ollama.

## Data and operating limits

Uploads, the document registry and vector index must be backed up together. Run **one backend worker**: the JSON registry lock is process-local and there is no cross-store transaction. Do not expose this app directly to the internet: user authentication, authorization, rate limits and durable multi-process storage are not implemented.

An empty retrieval result produces an explicit insufficient-evidence answer. Retrieved text is treated as untrusted, but prompt instructions are not a complete security boundary. OCR for scanned PDFs is not included. No accuracy, latency or production-readiness guarantee is claimed.

See [evaluation guidance](docs/EVALUATION.md) for the CS230-informed validation workflow.
