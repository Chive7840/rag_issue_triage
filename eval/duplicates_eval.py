"""Offline duplicate detection evaluation script using semantic retrieval."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
from sklearn.metrics import ndcg_score

from api.services import embeddings

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate duplicate issue detection")
    parser.add_argument("csv", type=Path, help="CSV file with columns id, title, body, duplicate_of")
    parser.add_argument("--k", type=int, default=5, help="Precision @ K cutoff")
    return parser.parse_args()

def compute_embeddings(df: pd.DataFrame) -> np.ndarray:
    texts = [f"{row.title}\n\n{row.body}" for row in df.itertuples(index=False)]
    return embeddings.encode_texts(texts)

def evaluate(df: pd.DataFrame, matrix: np.ndarray, k: int) -> dict[str, float]:
    similarities = matrix @ matrix.T
    np.fill_diagonal(similarities, -np.inf)
    hits = []
    precisions = []
    ndcgs: List[float] = []
    for idx, row in enumerate(df.itertuples(index=False)):
        if not row.duplicate_of:
            continue
        scores = similarities[idx]
        top_indices = np.argpartition(-scores, k)[:k]
        top_sorted = top_indices[np.argsort(-scores[top_indices])]
        retrieved_ids = df.iloc[top_sorted].id.tolist()
        target = row.duplicate_of
        hit = target in retrieved_ids
        hits.append(1 if hit else 0)
        relevant = [1 if issue_id == target else 0 for issue_id in retrieved_ids]
        precision = sum(relevant) / k
        precisions.append(precision)
        ndcg = ndcg_score([relevant], [scores[top_sorted]])
        ndcgs.append(float(ndcg))
    return {
        "count": len(hits),
        "hit_rate": float(np.mean(hits)) if hits else math.nan,
        "p@k": float(np.mean(precisions)) if precisions else math.nan,
        "ndcg": float(np.mean(ndcgs)) if ndcgs else math.nan,
    }

def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.csv)
    if not {"id", "title", "body", "duplicate_of"}.issubset(df.columns):
        raise ValueError("CSV must contain id, title, body, duplicate_of columns")
    matrix = compute_embeddings(df)
    metrics = evaluate(df, matrix, args.k)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
