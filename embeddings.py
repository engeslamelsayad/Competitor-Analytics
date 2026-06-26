"""
Voyage embeddings (voyage-3, 1024-dim).
Includes retry + back-off for 429 rate-limit errors on the free tier.
"""

import time
import requests

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

# Free tier limits: ~300 RPM, 1M tokens/min.
# 100 ads/batch with 2s sleep between batches stays well within limits.
BATCH_SIZE   = 25     # أصغر = أقل ضغط على الـ rate limit
RETRY_MAX    = 5      # محاولات أكثر
RETRY_DELAY  = 30     # انتظار أطول بعد كل 429


def creative_text(ad: dict) -> str:
    parts = [
        ad.get("page_name", ""),
        ad.get("title", ""),
        ad.get("body", ""),
        ad.get("description", ""),
    ]
    return "\n".join(p for p in parts if p).strip() or "(empty)"


class Embedder:
    def __init__(self, api_key: str, model: str = "voyage-3"):
        if not api_key:
            raise ValueError("VOYAGE_API_KEY is empty.")
        self.api_key  = api_key
        self.model    = model
        self.headers  = {"Authorization": f"Bearer {self.api_key}"}

    def _embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """Single batch call with retry on 429. Returns None if all retries fail."""
        for attempt in range(1, RETRY_MAX + 1):
            resp = requests.post(
                VOYAGE_URL,
                headers=self.headers,
                json={"input": texts, "model": self.model, "input_type": "document"},
                timeout=60,
            )
            if resp.status_code == 429:
                wait = RETRY_DELAY * attempt
                print(f"[embed] 429 rate-limit — waiting {wait}s (attempt {attempt}/{RETRY_MAX})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        # بدل الـ crash — نرجع None ونكمّل
        print(f"[embed] ⚠️ rate-limit exceeded after {RETRY_MAX} attempts — skipping this batch")
        return None

    def embed(self, texts: list[str], ad_ids: list[str] = None) -> dict[str, list[float]]:
        """Returns dict: ad_id → vector (skips failed batches gracefully)."""
        results: dict[str, list[float]] = {}
        total = len(texts)
        ids = ad_ids or [str(i) for i in range(total)]
        for i in range(0, total, BATCH_SIZE):
            batch_texts = texts[i : i + BATCH_SIZE]
            batch_ids   = ids[i : i + BATCH_SIZE]
            batch_num   = i // BATCH_SIZE + 1
            total_batches = (total - 1) // BATCH_SIZE + 1
            print(f"[embed] batch {batch_num}/{total_batches} ({len(batch_texts)} texts)")
            vectors = self._embed_batch(batch_texts)
            if vectors:
                for ad_id, vec in zip(batch_ids, vectors):
                    results[ad_id] = vec
            if i + BATCH_SIZE < total:
                time.sleep(3)   # pause بين الـ batches
        return results