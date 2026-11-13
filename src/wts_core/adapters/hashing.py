"""An embedder that needs no model: for tests, and for a site's offline sample data.

``HashingEmbedder`` is the one each site carried in ``embed/base.py``, unchanged: deterministic and offline, it
captures word overlap only. Its vectors are the same, number for number, as the sites' for the same texts. It needs
numpy and nothing else, imported when first used.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

__all__ = ["HashingEmbedder"]


def _normalise(m: Any) -> Any:
    """Rows scaled to length one, as 32-bit floats. A row of noughts stays as it is."""
    import numpy as np

    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class HashingEmbedder:
    """Feature-hashed unigrams + bigrams. Offline stand-in for tests and demos (``ports.Embedder``)."""

    _TOKEN = re.compile(r"[a-z0-9]+")

    def __init__(self, dim: int = 256):
        self.dim = self.dimension = dim
        self.name = self.id = f"hashing-{dim}"
        # cosine of unrelated text (floor) and of a strong match (ceiling) for this model
        self.similarity_range = (0.0, 0.6)

    def _vec(self, text: str) -> Any:
        import numpy as np

        v = np.zeros(self.dim, dtype=np.float32)
        toks = self._TOKEN.findall(text.lower())
        for gram in toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]:
            h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return v

    def embed_documents(self, texts: Sequence[str]) -> Any:
        import numpy as np

        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalise(np.stack([self._vec(t) for t in texts]))

    def embed_query(self, text: str) -> Any:
        return self.embed_documents([text])[0]
