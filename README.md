# Pulse RAG Manager

Unified document management + chat interface for the Pulse ERP support system.

## Prerequisites

- Python 3.10+
- Node.js 18+
- Ollama running locally with `llama3.2:3b` pulled

## Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open: http://localhost:5173

## Notes

- Uploaded files are stored in `uploads/`.
- Chroma DB persists in `rag_dbs/support_chroma_db`.
- Registry metadata is stored in `document_registry.json`.
