from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.common import BBoxModel
from app.schemas.search import SearchResponse
from app.services.discovery.service import DiscoveryService

router = APIRouter(prefix="/discovery", tags=["discovery"])


class SimilarSitesRequest(BBoxModel):
    tile_id: str
    top_k: int = Field(50, ge=1, le=500)
    min_quality: float | None = Field(None, ge=0, le=1)
    date_from: datetime | None = None
    date_to: datetime | None = None


class ClusterRequest(BBoxModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    algorithm: Literal["hdbscan", "kmeans", "dbscan"] = "hdbscan"
    min_cluster_size: int = Field(5, ge=2)
    n_clusters: int = Field(8, ge=2, le=1000, description="kmeans only")
    eps: float = Field(0.15, gt=0, description="dbscan only (cosine distance)")
    min_quality: float | None = Field(None, ge=0, le=1)


@router.post("/similar-sites", response_model=SearchResponse)
def similar_sites(req: SimilarSitesRequest, db: Session = Depends(get_db)):
    return DiscoveryService(db).similar_sites(req.tile_id, req.top_k, req.min_quality, req.bbox, req.date_from,
                                              req.date_to)


@router.post("/cluster")
def cluster(req: ClusterRequest, db: Session = Depends(get_db)):
    return DiscoveryService(db).cluster(req.bbox, req.date_from, req.date_to, req.algorithm, req.min_cluster_size,
                                        req.n_clusters, req.min_quality, req.eps)
