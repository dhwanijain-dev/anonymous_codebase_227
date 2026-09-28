from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.search import SearchFilters, SearchResponse, TextSearchRequest
from app.services.retrieval.service import RetrievalService, SearchParams

router = APIRouter(prefix="/search", tags=["search"])


def params_from(req: SearchFilters) -> SearchParams:
    return SearchParams(**req.model_dump(include=set(SearchParams.__dataclass_fields__) & set(type(req).model_fields)))


@router.post("/text", response_model=SearchResponse,
             summary="Natural-language semantic search with spatial/temporal/sensor filters and optional change verification")
def search_text(req: TextSearchRequest, db: Session = Depends(get_db)):
    return RetrievalService(db).search_text(req.query, params_from(req))


@router.get("/{query_id}", response_model=SearchResponse, summary="Retrieve a stored search and its ranked results")
def get_search(query_id: str, db: Session = Depends(get_db)):
    return RetrievalService(db).get_query(query_id)
