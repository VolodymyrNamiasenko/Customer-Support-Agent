from fastapi import APIRouter, Request, HTTPException
from typing import List
import os

from backend.models.schemas import ChatRequest, ChatResponse
from backend.services.retrieval import build_context
from backend.services.inference import run_inference
from backend.routers.reviews import store
from backend.services.retrieval_trace import retrieve_with_trace, runtime_provenance
from contextlib import nullcontext
from backend.hallucination_guard import validate_response

router = APIRouter()


def reviewed_draft(request, record, response):
    record = store(request).finish_attempt(record['id'], record['version'], response)
    return {**response, 'review_id': record['id'], 'review_status': record['status']}


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
    record = store(request).begin_attempt(payload.question)
    trace = None
    provenance = {"chat_model": "unknown", "chat_model_digest": None,
                  "embedding_model": "unknown", "embedding_revision": None}
    try:
        resolved = getattr(request.app.state, "pilot_provenance", None)
        provenance = resolved if resolved is not None else runtime_provenance(getattr(request.app.state, "embeddings", None))
        with getattr(request.app.state, "write_lock", nullcontext()):
            docs, trace = retrieve_with_trace(vectorstore, payload.question, payload.k, provenance)
        ownership = validate_response(payload.question + "\n" + build_context(docs), "")
        trace["ownership_relevant"] = bool(ownership.entity_is_integrated or ownership.has_non_creation_signal)
        trace["ownership_detection"] = "Question/context signals; absence is not proof of safe ownership"
        record = store(request).save_trace(record['id'], record['version'], trace)
    except Exception:
        if trace is None:
            record = store(request).save_trace(record['id'], record['version'], {
                "schema_version": "1.0", "status": "failed", "k": payload.k,
                "provenance": provenance, "hits": [], "used_context_chunk_ids": [],
                "claim_level_usage": "not_observed", "error": "retrieval_failed; results unknown",
            })
        store(request).finish_attempt(record['id'], record['version'], {
            "answer": "", "sources": [], "failure_stage": "retrieval",
            "hallucination_guard": {"is_valid": False},
        }, failed=True)
        raise HTTPException(503, detail={"message": "Retrieval failed", "review_id": record['id']}) from None
    if not docs:
        return reviewed_draft(request, record, {
            "answer": "I could not find supporting documentation. Please upload a relevant source or clarify your question.",
            "reasoning": "", "sources": [], "context_snippets": [],
            "hallucination_guard": {"is_valid": False, "entity_is_integrated": False, "has_non_creation_signal": False, "warning": "insufficient_evidence"},
        })
    context_text = build_context(docs)

    try:
        result, answer, check = run_inference(
            context_text=context_text,
            question=payload.question,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except Exception:
        store(request).finish_attempt(record['id'], record['version'], {
            "answer": "", "sources": _extract_sources(docs), "failure_stage": "generation",
            "hallucination_guard": {"is_valid": False},
        }, failed=True)
        raise HTTPException(503, detail={"message": "Generation failed", "review_id": record['id']}) from None

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

    return reviewed_draft(request, record, {
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
        "guard_replacement": not check.is_valid,
        "guard_relevant": trace["ownership_relevant"],
    })


@router.post("/v1/query", response_model=ChatResponse)
def query_v1(request: Request, payload: ChatRequest):
    return chat(request, payload)
