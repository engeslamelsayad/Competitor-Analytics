"""
Voyage embeddings (voyage-3, 1024-dim). Chosen over ada-002 for stronger Arabic.
Plain REST so we don't add an extra SDK dependency.
"""

import requests

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


def creative_text(ad: dict) -> str:
    """Join the creative fields into one string for embedding."""
    parts = [ad.get("page_name", ""), ad.get("title", ""),
             ad.get("body", ""), ad.get("description", "")]
    return "\n".join(p for p in parts if p).strip() or "(empty)"


class Embedder:
    def __init__(self, api_key: str, model: str = "voyage-3"):
        if not api_key:
            raise ValueError("VOYAGE_API_KEY is empty.")
        self.api_key = api_key
        self.model = model

    def embed(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        out: list[list[float]] = []
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = requests.post(
                VOYAGE_URL,
                headers=headers,
                json={"input": batch, "model": self.model, "input_type": "document"},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return out
