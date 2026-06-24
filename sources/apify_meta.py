"""
Apify-based Meta Ad Library source — field mapping verified against
the curious_coder/facebook-ads-library-scraper actor output (June 2026).

Key schema notes (from actual output):
  - body text lives at snapshot.body.text (it's a dict, not a string)
  - DCO ads use {{product.brand}} as body — real copy is in snapshot.cards[0]
  - start_date / end_date are Unix timestamps (integers), not ISO strings
  - start_date_formatted / end_date_formatted are human-readable strings
  - title and description live in snapshot.cards[0] for card-based creatives
  - ad_library_url is the public permalink → used as snapshot_url
  - publisher_platform is a list at the top level
"""

import requests
from datetime import datetime, timezone
from typing import Iterator
from .base import AdSource, NormalizedAd


def _ts_to_iso(ts) -> str | None:
    """Convert Unix timestamp (int/float) to ISO 8601 string, or return None."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _pick_text(snapshot: dict) -> str:
    """
    Extract the best available body text.
    Priority: first card body (real copy) → root body.text
    DCO ads set root body to {{product.brand}} — skip those.
    """
    # Try first card body
    cards = snapshot.get("cards") or []
    if cards:
        card_body = cards[0].get("body", "")
        if card_body and "{{" not in card_body:
            return card_body

    # Fall back to root body.text
    body_obj = snapshot.get("body") or {}
    root_text = body_obj.get("text", "") if isinstance(body_obj, dict) else str(body_obj)
    if root_text and "{{" not in root_text:
        return root_text

    # Nothing useful (pure DCO placeholder) — return empty
    return ""


def _pick_title(snapshot: dict) -> str:
    cards = snapshot.get("cards") or []
    if cards:
        return cards[0].get("title") or ""
    return snapshot.get("title") or ""


def _pick_description(snapshot: dict) -> str:
    cards = snapshot.get("cards") or []
    if cards:
        return cards[0].get("link_description") or ""
    return snapshot.get("link_description") or ""


class ApifyMetaSource(AdSource):
    name = "apify_meta"

    def __init__(self, token: str, actor: str):
        if not token:
            raise ValueError("APIFY_TOKEN is empty.")
        self.token = token
        self.actor = actor
        self.url = (
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
            f"?token={token}"
        )

    def fetch_ads(self, country, page_ids=None, search_terms=None,
                  limit=200) -> Iterator[NormalizedAd]:
        actor_input = {
            "count": limit,
            "country": country,
            "activeStatus": "active",
            "adType": "all",
        }
        if page_ids:
            actor_input["pageIds"] = page_ids
        if search_terms:
            actor_input["searchTerms"] = search_terms

        resp = requests.post(self.url, json=actor_input, timeout=600)
        resp.raise_for_status()

        for raw in resp.json():
            ad_id = str(raw.get("ad_archive_id", ""))
            if not ad_id:
                continue

            snapshot = raw.get("snapshot") or {}
            platforms = raw.get("publisher_platform") or []

            yield NormalizedAd(
                ad_id=ad_id,
                page_id=str(raw.get("page_id", "")),
                page_name=raw.get("page_name") or snapshot.get("page_name", ""),
                country=country,
                body=_pick_text(snapshot),
                title=_pick_title(snapshot),
                description=_pick_description(snapshot),
                link_caption=snapshot.get("caption", ""),
                platforms=",".join(platforms) if isinstance(platforms, list) else str(platforms),
                snapshot_url=raw.get("ad_library_url", ""),
                start_time=_ts_to_iso(raw.get("start_date")),
                stop_time=_ts_to_iso(raw.get("end_date")) if not raw.get("is_active") else None,
                source=self.name,
                extra={
                    "is_active": raw.get("is_active"),
                    "display_format": snapshot.get("display_format"),
                    "cta_text": snapshot.get("cta_text"),
                },
            )