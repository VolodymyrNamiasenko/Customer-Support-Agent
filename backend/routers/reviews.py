from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.services.reviews import ReviewConflict

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


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=80, pattern=r"\S")
    note: str = Field(default="", max_length=4000)
    decision: Literal["approved", "rejected"]


class RatingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=80, pattern=r"\S")
    note: str = Field(default="", max_length=4000)
    rating: int = Field(ge=1, le=5, strict=True)


@router.get("/metrics")
def metrics(request: Request):
    return store(request).metrics()


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


@router.get("/{identifier}/release")
def release(identifier: str, request: Request):
    return run(lambda: store(request).release(identifier))
