"""
Cluster creative embeddings into positioning themes (HDBSCAN), then label each
theme cheaply with Claude Haiku.

HDBSCAN (not K-means) because we don't know the number of themes in advance; it
finds arbitrarily many and drops noise. We L2-normalize first so plain euclidean
distance ranks like cosine similarity.
"""

import json
import numpy as np
from sklearn.cluster import HDBSCAN
from anthropic import Anthropic


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def cluster_ads(ads: list[dict], min_cluster_size: int = 4) -> list[dict]:
    """Group ads (each with an 'embedding') into theme clusters.
    Returns clusters: {ad_indices, size, competitor_count, sample_ads, centroid}."""
    if len(ads) < min_cluster_size:
        return []

    vectors = _normalize(np.array([a["embedding"] for a in ads], dtype=float))
    labels = HDBSCAN(min_cluster_size=min_cluster_size, copy=True).fit_predict(vectors)

    clusters = []
    for label in sorted(set(labels)):
        if label == -1:  # noise
            continue
        idx = [i for i, l in enumerate(labels) if l == label]
        members = [ads[i] for i in idx]
        centroid = vectors[idx].mean(axis=0)
        competitors = {m.get("page_name", "") for m in members}
        clusters.append({
            "ad_indices": idx,
            "size": len(idx),
            "competitor_count": len(competitors),
            "sample_ads": members[:5],
            "centroid": centroid.tolist(),
        })
    return clusters


LABEL_SYSTEM = """You name advertising themes. You receive clusters of ad texts.
For each cluster id, return a SHORT theme label (3-6 words, the language of the
ads). Return ONLY a JSON object mapping id -> label. No prose."""


def label_clusters(clusters: list[dict], api_key: str, model: str) -> None:
    """Mutate clusters in place, adding a 'theme' label to each."""
    if not clusters:
        return
    blob = {}
    for i, c in enumerate(clusters):
        samples = []
        for ad in c["sample_ads"]:
            txt = (ad.get("title") or "") + " " + (ad.get("body") or "")
            samples.append(txt.strip()[:200])
        blob[str(i)] = samples

    client = Anthropic(api_key=api_key) if api_key else Anthropic()
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=800,
            system=LABEL_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(blob, ensure_ascii=False)}],
        )
        text = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        labels = json.loads(text)
    except Exception:
        labels = {}

    for i, c in enumerate(clusters):
        c["theme"] = labels.get(str(i), f"theme_{i}")
