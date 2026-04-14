import hashlib
import os
from datetime import datetime, timezone
from typing import List, Tuple

import docx2txt
import pdfplumber
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from backend.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    HEADERS_TO_SPLIT_ON,
    SEPARATORS,
)


def _read_docx(path: str) -> str:
    return docx2txt.process(path) or ""


def _read_pdf(path: str) -> str:
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def _read_md(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_text(path: str, file_type: str) -> str:
    if file_type == "docx":
        return _read_docx(path)
    if file_type == "pdf":
        return _read_pdf(path)
    if file_type == "md":
        return _read_md(path)
    return ""


def chunk_text(
    text: str,
    source_path: str,
    filename: str,
    file_type: str,
) -> List[Document]:
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS_TO_SPLIT_ON)
    header_docs = markdown_splitter.split_text(text)

    for d in header_docs:
        d.metadata.update({"source": source_path})

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
    )

    chunks = text_splitter.split_documents(header_docs)

    upload_ts = datetime.now(timezone.utc).isoformat()
    for c in chunks:
        if "Section" in c.metadata:
            c.metadata["topic"] = c.metadata.get("Section", "").strip()
        c.metadata["manual_name"] = filename
        c.metadata["file_type"] = file_type
        c.metadata["upload_timestamp"] = upload_ts
        c.metadata["source"] = source_path
    return chunks


def build_chunk_ids(filename: str, chunks: List[Document]) -> List[str]:
    ids = []
    for idx, _ in enumerate(chunks):
        raw = f"{filename}:{idx}".encode("utf-8")
        ids.append(hashlib.sha256(raw).hexdigest())
    return ids
