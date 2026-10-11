"""Document ingestion with bounded uploads and serialized mutations."""
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, File, UploadFile, HTTPException, Request

from backend.config import ALLOWED_EXTENSIONS, UPLOAD_DIR
from backend.models.schemas import DocumentListResponse, UploadResponse
from backend.services.document_store import load_registry, upsert_document, remove_document
from backend.services.ingestion import extract_text, chunk_text, build_chunk_ids
from backend.services.file_safety import upload_path

router = APIRouter()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...)):
    try:
        path = upload_path(UPLOAD_DIR, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 20 MiB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")
    file_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    vectorstore = request.app.state.vectorstore
    # Use one worker: the registry and vector store are separate local stores.
    with request.app.state.write_lock:
        registry = load_registry()
        for name, entry in registry.documents.items():
            if name == file.filename or entry.get("file_hash") == file_hash:
                raise HTTPException(status_code=409, detail=f"Document already exists: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise HTTPException(status_code=409, detail="An unregistered file already uses this name.")
        ids = []
        try:
            with path.open("xb") as handle:
                handle.write(content)
            try:
                text = extract_text(str(path), ext.lstrip("."))
                chunks = chunk_text(text, str(path), file.filename, ext.lstrip("."))
            except Exception as exc:
                raise HTTPException(status_code=422, detail="Document could not be parsed.") from exc
            if not chunks:
                raise HTTPException(status_code=422, detail="Document contains no extractable text.")
            ids = build_chunk_ids(file.filename, chunks)
            vectorstore.add_documents(chunks, ids=ids)
            total_chunks = vectorstore._collection.count()
            upsert_document(file.filename, {
                "original_filename": file.filename,
                "file_hash": file_hash,
                "file_type": ext.lstrip("."),
                "upload_timestamp": datetime.now(timezone.utc).isoformat(),
                "file_path": str(path),
                "chunk_count": len(chunks),
                "chunk_ids": ids,
                "status": "indexed",
            })
        except Exception:
            try:
                if ids:
                    vectorstore.delete(ids=ids)
            finally:
                path.unlink(missing_ok=True)
            raise
    return {
        "status": "success", "filename": file.filename,
        "chunks_created": len(chunks), "total_chunks_in_db": total_chunks,
    }


@router.get("", response_model=DocumentListResponse)
def list_documents():
    registry = load_registry()
    documents = [
        {
            "filename": filename,
            "file_type": entry.get("file_type", ""),
            "upload_timestamp": entry.get("upload_timestamp", ""),
            "file_hash": entry.get("file_hash", ""),
            "chunk_count": entry.get("chunk_count", 0),
            "status": entry.get("status", "indexed"),
        }
        for filename, entry in registry.documents.items()
    ]
    return {
        "documents": documents, "total_documents": len(documents),
        "total_chunks": sum(int(item["chunk_count"]) for item in documents),
    }


@router.delete("/{filename}")
def delete_document(request: Request, filename: str):
    try:
        path = upload_path(UPLOAD_DIR, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with request.app.state.write_lock:
        entry = load_registry().documents.get(filename)
        if not entry:
            raise HTTPException(status_code=404, detail="Document not found.")
        if entry.get("chunk_ids"):
            request.app.state.vectorstore.delete(ids=entry["chunk_ids"])
        # Do not trust absolute paths in legacy registry entries.
        path.unlink(missing_ok=True)
        remove_document(filename)
    return {"status": "deleted"}
