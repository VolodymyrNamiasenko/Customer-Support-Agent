import os
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, File, UploadFile, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.config import ALLOWED_EXTENSIONS, UPLOAD_DIR
from backend.models.schemas import DocumentListResponse, UploadResponse
from backend.services.document_store import load_registry, upsert_document, remove_document
from backend.services.ingestion import extract_text, chunk_text, build_chunk_ids

router = APIRouter()


def _file_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"error": "Unsupported file type", "detail": ext},
        )

    content = await file.read()
    file_hash = _file_hash(content)

    registry = load_registry()
    for name, entry in registry.documents.items():
        if entry.get("file_hash") == file_hash:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "duplicate",
                    "message": f"File '{file.filename}' already exists in the knowledge base.",
                    "existing_file": name,
                },
            )

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(save_path, "wb") as f:
        f.write(content)

    text = extract_text(save_path, ext.lstrip("."))
    chunks = chunk_text(text, save_path, file.filename, ext.lstrip("."))
    ids = build_chunk_ids(file.filename, chunks)

    vectorstore = request.app.state.vectorstore
    lock = request.app.state.write_lock
    with lock:
        vectorstore.add_documents(chunks, ids=ids)

    chunk_count = len(chunks)
    total_chunks = vectorstore._collection.count()

    upsert_document(
        file.filename,
        {
            "original_filename": file.filename,
            "file_hash": file_hash,
            "file_type": ext.lstrip("."),
            "upload_timestamp": datetime.now(timezone.utc).isoformat(),
            "file_path": save_path,
            "chunk_count": chunk_count,
            "chunk_ids": ids,
            "status": "indexed",
        },
    )

    return {
        "status": "success",
        "filename": file.filename,
        "chunks_created": chunk_count,
        "total_chunks_in_db": total_chunks,
    }


@router.get("", response_model=DocumentListResponse)
def list_documents():
    registry = load_registry()
    documents = []
    total_chunks = 0
    for filename, entry in registry.documents.items():
        documents.append(
            {
                "filename": filename,
                "file_type": entry.get("file_type", ""),
                "upload_timestamp": entry.get("upload_timestamp", ""),
                "file_hash": entry.get("file_hash", ""),
                "chunk_count": entry.get("chunk_count", 0),
                "status": entry.get("status", "indexed"),
            }
        )
        total_chunks += int(entry.get("chunk_count", 0))
    return {
        "documents": documents,
        "total_documents": len(documents),
        "total_chunks": total_chunks,
    }


@router.delete("/{filename}")
def delete_document(request: Request, filename: str):
    registry = load_registry()
    entry = registry.documents.get(filename)
    if not entry:
        raise HTTPException(status_code=404, detail="Document not found.")

    vectorstore = request.app.state.vectorstore
    chunk_ids = entry.get("chunk_ids", [])
    if chunk_ids:
        lock = request.app.state.write_lock
        with lock:
            vectorstore.delete(ids=chunk_ids)

    file_path = entry.get("file_path")
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    remove_document(filename)
    return {"status": "deleted"}
