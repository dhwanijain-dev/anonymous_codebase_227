"""Stage-2 rankers. Weights come from Settings; nothing is hard-coded at call sites."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.models.base import ModelInfo, PluggableModel, config_checksum

COMPONENTS = ("semantic", "quality", "change", "metadata", "spatial", "temporal")


@dataclass
class Candidate:
    tile_id: str
    scores: dict[str, float] = field(default_factory=dict)  # component -> [0,1]
    applicable: set[str] = field(default_factory=set)  # components meaningful for this query
    penalty: float = 0.0  # feedback-derived penalty in [0,1]
    final_score: float = 0.0
    confidence: float = 0.0
    payload: dict = field(default_factory=dict)


class BaseRanker(PluggableModel, ABC):
    @abstractmethod
    def rank(self, candidates: list[Candidate]) -> list[Candidate]: ...


class WeightedRanker(BaseRanker):
    """final = sum(w_c * s_c) / sum(w_c) over *applicable* components, then feedback penalty.

    Components that do not apply to the query (e.g. `change` when require_change=false,
    `spatial` when no bbox) are dropped and the remaining weights renormalised, so scores
    stay comparable in [0,1]."""

    def __init__(self, weights: dict[str, float], version: str = "1.0.0"):
        unknown = set(weights) - set(COMPONENTS)
        if unknown:
            raise ValueError(f"Unknown ranking components: {unknown}")
        self.weights = {k: max(0.0, float(v)) for k, v in weights.items()}
        self.version = version

    def score(self, c: Candidate) -> float:
        comps = [k for k in COMPONENTS if k in c.applicable and self.weights.get(k, 0) > 0]
        wsum = sum(self.weights[k] for k in comps)
        if wsum == 0:
            return c.scores.get("semantic", 0.0)
        s = sum(self.weights[k] * float(c.scores.get(k, 0.0)) for k in comps) / wsum
        return s * (1.0 - c.penalty)

    def rank(self, candidates):
        for c in candidates:
            c.final_score = round(self.score(c), 6)
            # confidence: agreement of evidence — high only if the *weakest* key signal is decent
            keys = [c.scores.get(k, 0.0) for k in ("semantic", "quality", "change") if k in c.applicable]
            c.confidence = round(0.5 * c.final_score + 0.5 * (min(keys) if keys else c.final_score), 4)
        return sorted(candidates, key=lambda c: (-c.final_score, c.tile_id))

    def info(self):
        return ModelInfo("weighted-ranker", self.version, "reranker", None, config_checksum(self.weights),
                         "internal", "built-in", {"components": list(COMPONENTS)}, {"weights": self.weights})
