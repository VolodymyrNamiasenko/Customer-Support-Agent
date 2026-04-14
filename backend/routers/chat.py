from fastapi import APIRouter, Request
from typing import List
import os

from backend.models.schemas import ChatRequest, ChatResponse
from backend.services.retrieval import deduplicate_docs, tag_sources, build_context
from backend.services.inference import run_inference

router = APIRouter()


def _extract_sources(docs) -> List[str]:
    sources = set()
    for d in docs:
        src = d.metadata.get("source", "")
        if src:
            sources.add(os.path.basename(src).replace(".docx", ""))
    return sorted(list(sources))


@router.post("/chat", response_model=ChatResponse)
def chat(request: Request, payload: ChatRequest):
    vectorstore = request.app.state.vectorstore
    docs = vectorstore.similarity_search(payload.question, k=payload.k)
    docs = deduplicate_docs(docs)
    docs = tag_sources(docs)
    context_text = build_context(docs)

    result, answer, check = run_inference(
        context_text=context_text,
        question=payload.question,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )

    sources = _extract_sources(docs)
    context_snippets = []
    for d in docs:
        context_snippets.append(
            {
                "source": d.metadata.get("source", ""),
                "tag": d.metadata.get("tag", "[MANUAL]"),
                "preview": d.page_content[:300],
            }
        )

    return {
        "answer": answer,
        "reasoning": getattr(result, "reasoning", ""),
        "sources": sources,
        "hallucination_guard": {
            "is_valid": check.is_valid,
            "entity_is_integrated": check.entity_is_integrated,
            "has_non_creation_signal": check.has_non_creation_signal,
            "has_safe_response": bool(getattr(check, "matched_safe_signals", [])),
            "warning": check.warning or None,
        },
        "context_snippets": context_snippets,
    }


@router.post("/v1/query", response_model=ChatResponse)
def query_v1(request: Request, payload: ChatRequest):
    return chat(request, payload)
