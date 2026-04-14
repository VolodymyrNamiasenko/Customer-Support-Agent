from fastapi import APIRouter, Request, Query
from typing import Optional

from backend.models.schemas import ChunkListResponse

router = APIRouter()


@router.get("/chunks", response_model=ChunkListResponse)
def list_chunks(
    request: Request,
    filename: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    vectorstore = request.app.state.vectorstore
    chunks = []
    total = 0

    if search:
        kwargs = {}
        if filename:
            kwargs["filter"] = {"manual_name": filename}
        results = vectorstore.similarity_search_with_relevance_scores(search, k=limit, **kwargs)
        total = len(results)
        for doc, score in results:
            chunks.append(
                {
                    "id": doc.metadata.get("id", ""),
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "content_preview": doc.page_content[:300],
                    "score": score,
                }
            )
    else:
        where = {"manual_name": filename} if filename else None
        data = vectorstore._collection.get(
            where=where,
            include=["documents", "metadatas", "ids"],
            limit=limit,
            offset=offset,
        )
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        total = len(docs)
        for doc, meta, doc_id in zip(docs, metas, ids):
            chunks.append(
                {
                    "id": doc_id,
                    "content": doc,
                    "metadata": meta or {},
                    "content_preview": (doc or "")[:300],
                }
            )

    return {"chunks": chunks, "total": total, "limit": limit, "offset": offset}
