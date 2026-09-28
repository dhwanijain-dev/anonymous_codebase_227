"""Embedding models. Real models are loaded strictly from the local filesystem."""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from app.core.exceptions import ModelLoadError
from app.geo import spectral
from app.models.base import ModelInfo, PluggableModel, config_checksum, load_model_card, path_checksum
from app.models.concepts import CONCEPTS


def l2n(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


class BaseEmbeddingModel(PluggableModel, ABC):
    """Images are normalised reflectance arrays (bands, H, W) in [0,1] plus a valid mask."""

    @abstractmethod
    def encode_image(self, image: np.ndarray, valid: np.ndarray | None = None,
                     clear: np.ndarray | None = None) -> np.ndarray: ...

    def encode_images(self, images: list[tuple[np.ndarray, np.ndarray | None, np.ndarray | None]]) -> np.ndarray:
        return np.stack([self.encode_image(*x) for x in images]) if images else np.zeros(
            (0, self.embedding_dimension()), np.float32)

    @abstractmethod
    def encode_text(self, text: str) -> np.ndarray: ...

    @abstractmethod
    def embedding_dimension(self) -> int: ...

    @property
    def supports_text(self) -> bool:
        return True


class MockEmbeddingModel(BaseEmbeddingModel):
    """Deterministic, training-free joint image/text space.

    Images -> 16-d spectral/structural descriptor -> standardise -> fixed seeded random
    projection -> L2. Text -> concept prototypes in the same 16-d space (+ a small hashed
    component for unknown words) -> same projection. Because both modalities share the
    descriptor space, 'water', 'vegetation', 'built structures' etc. retrieve plausibly."""

    def __init__(self, name: str, version: str, dim: int, band_mapping: dict[str, int], seed: int = 1337):
        self.name, self.version, self.dim = name, version, dim
        self.band_mapping = band_mapping
        rng = np.random.default_rng(seed)
        self.proj = rng.standard_normal((spectral.N_FEATURES, dim)).astype(np.float32) / np.sqrt(dim)
        self._cfg = {"kind": "mock", "dim": dim, "seed": seed, "features": spectral.FEATURE_NAMES}

    def embedding_dimension(self) -> int:
        return self.dim

    def _project(self, z: np.ndarray) -> np.ndarray:
        return l2n(z @ self.proj)

    def encode_image(self, image, valid=None, clear=None):
        if valid is None:
            valid = image.max(axis=0) > 0
        desc = spectral.descriptor(image, valid, self.band_mapping, clear)
        return self._project(spectral.standardize(desc))

    def encode_text(self, text: str) -> np.ndarray:
        t = text.lower()
        z = np.zeros(spectral.N_FEATURES, dtype=np.float32)
        matched = 0
        for _concept, (syns, _cat, proto) in CONCEPTS.items():
            hits = sum(1 for s in syns if re.search(rf"\b{re.escape(s)}\b", t))
            if hits:
                z += proto * (1.0 + 0.25 * (hits - 1))
                matched += 1
        # deterministic hashed residual so unknown queries still map to a stable vector
        for w in re.findall(r"[a-z]{3,}", t):
            h = int(hashlib.sha256(w.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(h)
            z += rng.standard_normal(spectral.N_FEATURES).astype(np.float32) * (0.05 if matched else 0.5)
        return self._project(z)

    def info(self) -> ModelInfo:
        return ModelInfo(self.name, self.version, "embedding", None, config_checksum(self._cfg),
                         "internal", "built-in deterministic mock",
                         {"image": "float32[bands,H,W] reflectance 0-1", "text": "str"},
                         {"embedding": f"float32[{self.dim}] L2-normalised"})


class RemoteSensingEmbeddingModel(BaseEmbeddingModel):
    """Loads a TorchScript remote-sensing encoder from a LOCAL directory. Never downloads.

    Expected layout (EMBEDDING_MODEL_PATH may point at the dir or image_encoder.pt):
        model_dir/
          image_encoder.pt     TorchScript: float[B,C,H,W] -> float[B,D]
          text_encoder.pt      optional TorchScript: int64[B,T] -> float[B,D]
          tokenizer.json       optional, HF `tokenizers` file (loaded offline)
          model_card.json      {name, version, license, source, dimension, input_size,
                                bands:[1-based indices], mean:[..], std:[..], context_length}
    Suitable sources: exported RemoteCLIP / GeoRSCLIP / SatCLIP / Prithvi encoders.
    """

    def __init__(self, model_path: str, name: str, version: str, dim: int, device: str = "cpu",
                 license: str | None = None, source: str | None = None):
        try:
            import torch
        except ImportError as e:
            raise ModelLoadError("PyTorch is required for RemoteSensingEmbeddingModel") from e
        self.torch = torch
        p = Path(model_path)
        self.dir = p if p.is_dir() else p.parent
        img = self.dir / "image_encoder.pt" if p.is_dir() else p
        if not img.exists():
            raise ModelLoadError(f"Embedding model not found at {img} (models must be staged locally)")
        self.card = load_model_card(self.dir)
        self.name = self.card.get("name", name)
        self.version = str(self.card.get("version", version))
        self.dim = int(self.card.get("dimension", dim))
        self.license = self.card.get("license", license)
        self.source = self.card.get("source", source)
        self.device = device
        self.image_encoder = torch.jit.load(str(img), map_location=device).eval()
        txt = self.dir / "text_encoder.pt"
        self.text_encoder = torch.jit.load(str(txt), map_location=device).eval() if txt.exists() else None
        self.tokenizer = None
        tok = self.dir / "tokenizer.json"
        if tok.exists():
            from tokenizers import Tokenizer

            self.tokenizer = Tokenizer.from_file(str(tok))
        self.input_size = int(self.card.get("input_size", 224))
        self.bands = self.card.get("bands")
        self.mean = np.array(self.card.get("mean", [0.0]), dtype=np.float32)
        self.std = np.array(self.card.get("std", [1.0]), dtype=np.float32)
        self._checksum = path_checksum(self.dir)

    @property
    def supports_text(self) -> bool:
        return self.text_encoder is not None and self.tokenizer is not None

    def embedding_dimension(self) -> int:
        return self.dim

    def _prep(self, image: np.ndarray) -> np.ndarray:
        x = image[[b - 1 for b in self.bands]] if self.bands else image
        mean = self.mean[:, None, None] if self.mean.size == x.shape[0] else self.mean.mean()
        std = self.std[:, None, None] if self.std.size == x.shape[0] else self.std.mean()
        return ((x - mean) / std).astype(np.float32)

    def encode_images(self, images):
        torch = self.torch
        if not images:
            return np.zeros((0, self.dim), np.float32)
        batch = torch.from_numpy(np.stack([self._prep(im) for im, _, _ in images])).to(self.device)
        batch = torch.nn.functional.interpolate(batch, size=(self.input_size, self.input_size),
                                                mode="bilinear", align_corners=False)
        with torch.inference_mode():
            out = self.image_encoder(batch).float().cpu().numpy()
        return l2n(out)

    def encode_image(self, image, valid=None, clear=None):
        return self.encode_images([(image, valid, clear)])[0]

    def encode_text(self, text: str) -> np.ndarray:
        if not self.supports_text:
            raise ModelLoadError(f"Model {self.name} has no local text encoder/tokenizer")
        torch = self.torch
        ctx = int(self.card.get("context_length", 77))
        ids = self.tokenizer.encode(text).ids[:ctx]
        ids = ids + [0] * (ctx - len(ids))
        with torch.inference_mode():
            out = self.text_encoder(torch.tensor([ids], dtype=torch.long, device=self.device))
        return l2n(out.float().cpu().numpy()[0])

    def info(self) -> ModelInfo:
        return ModelInfo(self.name, self.version, "embedding", str(self.dir), self._checksum,
                         self.license, self.source,
                         {"image": f"float32[C,{self.input_size},{self.input_size}]", "bands": self.bands},
                         {"embedding": f"float32[{self.dim}]"})
