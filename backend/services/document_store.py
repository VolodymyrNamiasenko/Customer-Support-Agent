import json
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any
from threading import RLock

from backend.config import DOCUMENT_REGISTRY


_lock = RLock()


@dataclass
class DocumentRegistry:
    documents: Dict[str, Dict[str, Any]]


def _ensure_registry():
    if not os.path.exists(DOCUMENT_REGISTRY):
        save_registry(DocumentRegistry(documents={}))


def load_registry() -> DocumentRegistry:
    with _lock:
        _ensure_registry()
        with open(DOCUMENT_REGISTRY, "r", encoding="utf-8") as f:
            data = json.load(f)
    return DocumentRegistry(documents=data.get("documents", {}))


def save_registry(registry: DocumentRegistry) -> None:
    with _lock:
        path = Path(DOCUMENT_REGISTRY)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".registry-")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"documents": registry.documents}, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def upsert_document(filename: str, payload: Dict[str, Any]) -> None:
    with _lock:
        registry = load_registry()
        registry.documents[filename] = payload
        save_registry(registry)


def remove_document(filename: str) -> None:
    with _lock:
        registry = load_registry()
        if filename in registry.documents:
            registry.documents.pop(filename)
            save_registry(registry)
