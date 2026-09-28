"""Ranking lives in app.models.reranker (pluggable); the configured instance comes from the registry."""
from app.models.reranker import BaseRanker, Candidate, WeightedRanker  # noqa: F401
from app.services.registry import get_ranker  # noqa: F401
