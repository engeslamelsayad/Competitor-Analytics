"""
Apify Meta Ad Library source — input schema verified from
curious_coder/facebook-ads-library-scraper (June 2026).

Actor input schema (actual):
  {
    "count": 100,
    "scrapeAdDetails": false,
    "scrapePageAds.activeStatus": "active",
    "scrapePageAds.countryCode": "SA",
    "scrapePageAds.sortBy": "impressions_desc",
    "urls": [
      {"url": "https://www.facebook.com/ads/library/?..."},
      {"url": "https://www.facebook.com/PageName"}
    ]
  }

Two URL patterns supported:
  1. Ad Library search URL  → search by keyword per country
  2. Facebook Page URL      → all ads for a specific competitor page
"""

import requests
from datetime import datetime, timezone
from typing import Iterator
from .base import AdSource, NormalizedAd


def _ts_to_iso(ts) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _pick_text(snapshot: dict) -> str:
    cards = snapshot.get("cards") or []
    if cards:
        card_body = cards[0].get("body", "")
        if card_body and "{{" not in card_body:
            return card_body
    body_obj = snapshot.get("body") or {}
    root_text = body_obj.get("text", "") if isinstance(body_obj, dict) else str(body_obj)
    if root_text and "{{" not in root_text:
        return root_text
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


def _build_library_url(country: str, search_term: str) -> str:
    """Build Facebook Ad Library search URL for a keyword + country."""
    import urllib.parse
    params = {
        "active_status": "active",
        "ad_type": "all",
        "country": country,
        "q": search_term,
        "search_type": "keyword_unordered",
        "media_type": "all",
    }
    return "https://www.facebook.com/ads/library/?" + urllib.parse.urlencode(params)


def _build_page_url(page_id: str) -> str:
    """Facebook Page URL — actor will scrape all ads for this page."""
    return f"https://www.facebook.com/{page_id}"


class ApifyMetaSource(AdSource):
    name = "apify_meta"

    def __init__(self, token: str, actor: str):
        if not token:
            raise ValueError("APIFY_TOKEN is empty.")
        self.token = token
        self.actor = actor
        # Use actor ID with ~ separator
        self.url = (
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
            f"?token={token}"
        )

    def fetch_ads(self, country, page_ids=None, search_terms=None,
                  limit=200) -> Iterator[NormalizedAd]:

        # Build the urls list (actor's required format)
        urls = []

        if page_ids:
            for pid in page_ids:
                urls.append({"url": _build_page_url(pid)})

        if search_terms:
            for term in search_terms:
                urls.append({"url": _build_library_url(country, term)})

        if not urls:
            print(f"[apify_meta] no page_ids or search_terms — skipping {country}")
            return

        actor_input = {
            "count": limit,
            "scrapeAdDetails": False,
            "scrapePageAds.activeStatus": "active",
            "scrapePageAds.countryCode": country,
            "scrapePageAds.sortBy": "impressions_desc",
            "urls": urls,
        }

        try:
            resp = requests.post(self.url, json=actor_input, timeout=600)
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"[apify_meta] HTTP error {e.response.status_code}: {e.response.text[:200]}")
            return
        except Exception as e:
            print(f"[apify_meta] request failed: {e}")
            return

        items = resp.json()
        if not isinstance(items, list):
            print(f"[apify_meta] unexpected response type: {type(items)}")
            return

        for raw in items:
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