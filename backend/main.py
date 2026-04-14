import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from threading import Lock
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from backend.config import CHROMA_PERSIST_DIR, EMBEDDING_MODEL, UPLOAD_DIR
from backend.routers import documents, rag, chat
from backend.services.document_store import load_registry


def create_app() -> FastAPI:
    app = FastAPI(title="Pulse RAG Manager", version="1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "request_failed", "detail": exc.detail},
        )

    @app.on_event("startup")
    def startup():
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        load_registry()
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        vectorstore = Chroma(persist_directory=CHROMA_PERSIST_DIR, embedding_function=embeddings)
        app.state.embeddings = embeddings
        app.state.vectorstore = vectorstore
        app.state.write_lock = Lock()

    app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
    app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    return app


app = create_app()
