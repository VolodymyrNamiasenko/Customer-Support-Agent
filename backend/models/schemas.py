from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class DocumentItem(BaseModel):
    filename: str
    file_type: str
    upload_timestamp: str
    file_hash: str
    chunk_count: int
    status: str


class DocumentListResponse(BaseModel):
    documents: List[DocumentItem]
    total_documents: int
    total_chunks: int


class UploadResponse(BaseModel):
    status: str
    filename: str
    chunks_created: int
    total_chunks_in_db: int


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class ChatRequest(BaseModel):
    question: str
    k: int = Field(default=5, ge=1, le=15)
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(default=512, ge=1)


class ContextSnippet(BaseModel):
    source: str
    tag: str
    preview: str


class GuardResult(BaseModel):
    is_valid: bool
    entity_is_integrated: bool
    has_non_creation_signal: bool
    has_safe_response: Optional[bool] = None
    warning: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    reasoning: str
    sources: List[str]
    hallucination_guard: GuardResult
    context_snippets: List[ContextSnippet]


class ChunkItem(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any]
    content_preview: str
    score: Optional[float] = None


class ChunkListResponse(BaseModel):
    chunks: List[ChunkItem]
    total: int
    limit: int
    offset: int
