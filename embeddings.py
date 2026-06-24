"""
Voyage embeddings (voyage-3, 1024-dim).
Includes retry + back-off for 429 rate-limit errors on the free tier.
"""

import time
import requests

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

# Free tier limits: ~300 RPM, 1M tokens/min.
# 100 ads/batch with 2s sleep between batches stays well within limits.
BATCH_SIZE   = 50     # ads per API call (conservative)
RETRY_MAX    = 4      # number of retries on 429
RETRY_DELAY  = 15     # seconds to wait after a 429


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

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Single batch call with retry on 429."""
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
        raise RuntimeError("Voyage rate-limit: max retries exceeded.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        total = len(texts)
        for i in range(0, total, BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            print(f"[embed] batch {i//BATCH_SIZE + 1}/{(total-1)//BATCH_SIZE + 1} ({len(batch)} texts)")
            out.extend(self._embed_batch(batch))
            if i + BATCH_SIZE < total:
                time.sleep(2)   # gentle pause between batches
        return out