"""Lazy sentence-transformers encoder for article titles.

Descendant of the removed tools/embedder.py (see git history 41e0c29~1):
EmbeddingGemma-300M in bf16 was the best speed/quality trade-off we
measured on this corpus, and it is multilingual — which matters because
most of the collected news is not English.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np  # ty: ignore[unresolved-import] — digest extra

DEFAULT_MODEL = "google/embeddinggemma-300m"
DEFAULT_DTYPE = "bfloat16"
# Gemma ships task-specific prompt templates; Clustering emits vectors
# tuned for grouping near-duplicate texts, which is exactly this job.
PREFERRED_PROMPT = "Clustering"


class TitleEmbedder:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        batch_size: int = 128,
        dtype: Optional[str] = DEFAULT_DTYPE,
        device: Optional[str] = None,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self.dtype = dtype
        self.device = device
        self._model = None
        self._prompt_name: Optional[str] = None

    def _ensure_model(self):
        if self._model is None:
            import torch  # ty: ignore[unresolved-import] — digest extra
            from sentence_transformers import SentenceTransformer  # ty: ignore[unresolved-import] — digest extra

            kwargs = {}
            if self.dtype:
                kwargs["model_kwargs"] = {"torch_dtype": getattr(torch, self.dtype)}
            if self.device:
                kwargs["device"] = self.device
            self._model = SentenceTransformer(self.model_name, **kwargs)
            prompts = getattr(self._model, "prompts", None) or {}
            self._prompt_name = PREFERRED_PROMPT if PREFERRED_PROMPT in prompts else None
        return self._model

    def encode(self, titles: List[str], progress: bool = False) -> np.ndarray:
        """Encode titles into L2-normalized float32 vectors."""
        model = self._ensure_model()
        emb = model.encode(
            titles,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            prompt_name=self._prompt_name,
            show_progress_bar=progress,
            convert_to_numpy=True,
        )
        return np.asarray(emb, dtype=np.float32)
