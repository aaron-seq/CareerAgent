"""
Pluggable text embeddings.

Two implementations behind one small protocol:

* :class:`HashingEmbedder` -- deterministic feature-hashing bag-of-words,
  needs no model download and no network. Used in tests and offline runs.
* :class:`SentenceTransformerEmbedder` -- wraps ``all-MiniLM-L6-v2`` when the
  optional ``sentence-transformers`` package (and its model) are available.

:func:`get_embedder` returns the semantic one if installed, else the hashing
fallback, so callers never have to branch. Both L2-normalize, so a dot product
is cosine similarity.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol, runtime_checkable

import numpy as np

_TOKEN = re.compile(r"[a-z0-9+#.]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word/skill tokens (keeps c++, c#, .net, node.js-ish tokens).

    Strips a trailing sentence-ending period ("built." -> "built") since the
    token regex keeps '.' for embedded dots (.net, node.js) and can't tell
    those apart from one glued on by prose -- but a *trailing* dot is always
    punctuation, never part of a real token, so it's safe to drop.
    """
    tokens = (t.rstrip(".") for t in _TOKEN.findall((text or "").lower()))
    return [t for t in tokens if t]


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic feature-hashing embedder (no dependencies to download)."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float64)
        for tok in tokenize(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            # Signed hashing reduces collisions cancelling out systematically.
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class SentenceTransformerEmbedder:
    """Semantic embedder using sentence-transformers (optional dependency)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # lazy, optional

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]


def get_embedder(prefer_semantic: bool = True) -> Embedder:
    """Return the best available embedder.

    Falls back to :class:`HashingEmbedder` when sentence-transformers (or its
    model) can't be loaded -- e.g. offline environments.
    """
    if prefer_semantic:
        try:
            return SentenceTransformerEmbedder()
        except Exception:
            pass
    return HashingEmbedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors (0 if either is empty/zero)."""
    if not a or not b:
        return 0.0
    va, vb = np.asarray(a), np.asarray(b)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
