"""Common model metadata so every pluggable model can be registered + versioned."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ModelInfo:
    name: str
    version: str
    type: str  # embedding | change | quality | reranker | parser
    local_path: str | None = None
    checksum: str | None = None
    license: str | None = None
    source: str | None = None
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    def to_dict(self) -> dict:
        return asdict(self)


def path_checksum(path: str | Path) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
    for f in files:
        with open(f, "rb") as fh:
            while chunk := fh.read(1 << 20):
                h.update(chunk)
    return h.hexdigest()


def config_checksum(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()


def load_model_card(model_path: str | Path) -> dict:
    """Read <model_dir>/model_card.json (name, version, license, source, dimension, ...)."""
    p = Path(model_path)
    card = (p if p.is_dir() else p.parent) / "model_card.json"
    return json.loads(card.read_text()) if card.exists() else {}


class PluggableModel:
    def info(self) -> ModelInfo:  # pragma: no cover - interface
        raise NotImplementedError
