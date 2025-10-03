"""Embedding utilities built on top of sentence-transformers for GitHub issue text."""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable

import numpy as np
from sentence_transformers import SentenceTransformer

from api.utils.logging_utils import get_logger, logging_context

logger = get_logger("api.services.embeddings")

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

@lru_cache(maxsize=1)
def get_model(model_name : str = DEFAULT_MODEL) -> SentenceTransformer:
    with logging_context(component="embeddings", model=model_name):
        logger.info("Loading embedding model")
    return SentenceTransformer(model_name)

def encode_texts(texts: Iterable[str], model_name: str = DEFAULT_MODEL) -> np.ndarray:
    model = get_model(model_name)
    embeddings = model.encode(list(texts), convert_to_numpy=True, show_progress_bar=True, normalize_embeddings=True)
    return embeddings.astype(np.float32)

def embedding_for_issue(title: str, body: str, model_name: str = DEFAULT_MODEL) -> np.ndarray:
    text = f"{title}\n\n{body}".strip()
    embedding = encode_texts([text], model_name=model_name)
    return embedding[0]
