import json
import os
from dataclasses import dataclass
from typing import Dict, Any
from threading import Lock

from backend.config import DOCUMENT_REGISTRY


_lock = Lock()


@dataclass
class DocumentRegistry:
    documents: Dict[str, Dict[str, Any]]


def _ensure_registry():
    if not os.path.exists(DOCUMENT_REGISTRY):
        with open(DOCUMENT_REGISTRY, "w", encoding="utf-8") as f:
            json.dump({"documents": {}}, f, ensure_ascii=False, indent=2)


def load_registry() -> DocumentRegistry:
    _ensure_registry()
    with _lock:
        with open(DOCUMENT_REGISTRY, "r", encoding="utf-8") as f:
            data = json.load(f)
    return DocumentRegistry(documents=data.get("documents", {}))


def save_registry(registry: DocumentRegistry) -> None:
    _ensure_registry()
    with _lock:
        with open(DOCUMENT_REGISTRY, "w", encoding="utf-8") as f:
            json.dump({"documents": registry.documents}, f, ensure_ascii=False, indent=2)


def upsert_document(filename: str, payload: Dict[str, Any]) -> None:
    registry = load_registry()
    registry.documents[filename] = payload
    save_registry(registry)


def remove_document(filename: str) -> None:
    registry = load_registry()
    if filename in registry.documents:
        registry.documents.pop(filename)
        save_registry(registry)
