from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.services.reviews import ReviewConflict
from backend.services.pilot import CORRECTNESS, TAXONOMY

router = APIRouter()


def store(request):
    instance = getattr(request.app.state, "review_store", None)
    if instance is None:
        raise HTTPException(503, "Review storage is not ready")
    return instance


def run(operation):
    try:
        return operation()
    except KeyError:
        raise HTTPException(404, "Response not found") from None
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=80, pattern=r"\S")
    note: str = Field(default="", max_length=4000)
    decision: Literal["approved", "rejected"]


class RatingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    # Backward-compatible input only. Never retained, hashed or logged.
    actor: str = Field(default="anonymous_customer", max_length=80)
    note: str = Field(default="", max_length=4000)
    rating: int = Field(ge=1, le=5, strict=True)


@router.get("/metrics")
def metrics(request: Request):
    return {**store(request).metrics(), "pilot": store(request).pilot_metrics()}


class ExpertInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    correctness: Literal["correct", "partially_correct", "incorrect"]
    error_bucket: str | None = None
    rationale: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(min_length=1, max_length=20)


@router.get("/expert-queue")
def expert_queue(request: Request, limit: int = Query(25, ge=1, le=100),
                 offset: int = Query(0, ge=0), include_reviewed: bool = False):
    return store(request).expert_queue(limit, offset, include_reviewed)


@router.get("/expert-policy")
def expert_policy(request: Request):
    return {"policy": store(request).policy(), "correctness": CORRECTNESS, "error_buckets": TAXONOMY}


class CorpusPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["upload", "delete", "retrieval_config"]
    filename: str = Field(min_length=1, max_length=255)
    file_sha256: str | None = None
    before_run: str
    after_run: str
    verdict_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=4000)
    actor: str = Field(min_length=1, max_length=80)


@router.post("/corpus-changes")
def propose_change(payload: CorpusPlanInput, request: Request):
    return {"change_id": run(lambda: store(request).propose_corpus_change(payload.model_dump()))}


@router.get("")
def listing(
    request: Request,
    status: Literal["pending", "approved", "rejected"] | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return store(request).list(status, limit, offset)


@router.get("/{identifier}")
def detail(identifier: str, request: Request):
    return run(lambda: store(request).get(identifier))


@router.post("/{identifier}/decision")
def decide(identifier: str, payload: ReviewInput, request: Request):
    return run(
        lambda: store(request).update(
            identifier,
            payload.version,
            payload.actor,
            payload.note,
            decision=payload.decision,
        )
    )


@router.post("/{identifier}/rating")
def rate(identifier: str, payload: RatingInput, request: Request):
    return run(
        lambda: store(request).update(
            identifier,
            payload.version,
            payload.actor,
            payload.note,
            rating=payload.rating,
        )
    )


@router.post("/{identifier}/expert-verdict")
def expert_verdict(identifier: str, payload: ExpertInput, request: Request):
    return run(lambda: store(request).expert_verdict(identifier, payload.version, payload.correctness,
               payload.error_bucket, payload.rationale, payload.evidence))


@router.get("/{identifier}/release")
def release(identifier: str, request: Request):
    return run(lambda: store(request).release(identifier))
