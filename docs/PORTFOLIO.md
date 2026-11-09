# Portfolio evidence and acceptance checks

This repository demonstrates a document-grounded ERP/MES support prototype. It does not contain workplace pilot records, client data or proof of a measured production outcome.

| Capability | Implementation | Boundary |
| --- | --- | --- |
| Document-grounded answers | `backend/services/ingestion.py`, `retrieval.py`, `inference.py` | Retrieval does not establish factual correctness |
| Source references | `backend/routers/chat.py` and frontend `ChatMessage.jsx` | Lists retrieved documents, not verified claim-level citations |
| Response checks and business restrictions | `backend/hallucination_guard.py`, `rules_config.py` | Regex/keyword heuristics can overblock or miss unsafe advice |
| Human review | Source and guard information shown in the interface | User-led review, not an enforced approval queue |
| Model stack | FastAPI, DSPy, Ollama, Chroma, sentence embeddings, React | No live ERP/MES transactions or autonomous system writes |

The professional pilot and any user-rated questions described in the author's experience are separate from repository verification. No private feedback is published here and no benchmark is inferred from those statements.

## Reproducible checks

Run `python -m unittest discover -s tests -v` from the repository root and `npm ci && npm run build` from `frontend`. Tests use temporary stores and mocked inference; they verify software contracts, not model quality.

For manual acceptance, start the app as described in the README and use only `examples/synthetic_support_guide.md`:

1. Upload the guide and inspect its indexed text in the explorer.
2. Ask which system owns Demo Orders; verify the retrieved source and restriction manually.
3. Upload the same file again; expect a duplicate error without overwriting evidence.
4. Remove the guide and ask again with an empty index; expect insufficient-evidence feedback.
5. Stop Ollama and send a question with evidence indexed; expect a visible error, not a silent stalled chat.

Record actual observed behavior, model/version, fixture, date, and reviewer before reporting results. Live Ollama/embedding acceptance is separate from the automated mocked tests. See `EVALUATION.md` for held-out evaluation and error analysis.
