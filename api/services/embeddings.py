"""Embedding utilities built on top of sentence-transformers for GitHub issue text."""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable
import logging
from custom_logger.logger import Logger
logging.setLoggerClass(Logger)
logger = logging.getLogger(__name__)

import numpy as np
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

@lru_cache(maxsize=1)
def get_model(model_name : str = DEFAULT_MODEL) -> SentenceTransformer:
    logger.info("Loading embedding model %s", model_name)
    return SentenceTransformer(model_name)

def encode_texts(texts: Iterable[str], model_name: str = DEFAULT_MODEL) -> np.ndarray:
    model = get_model(model_name)
    embeddings = model.encode(list(texts), convert_to_numpy=True, show_progress_bar=True, normalize_embeddings=True)
    return embeddings.astype(np.float32)

def embedding_for_issue(title: str, body: str, model_name: str = DEFAULT_MODEL) -> np.ndarray:
    text = f"{title}\n\n{body}".strip()
    embedding = encode_texts([text], model_name=model_name)
    return embedding[0]
