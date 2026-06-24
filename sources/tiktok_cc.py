"""
TikTok Creative Center source via doliz/tiktok-creative-center-scraper.

Input schema verified from Apify actor UI (June 2026).

IMPORTANT: This actor requires TikTok login cookies.
  1. Log into ads.tiktok.com/creative_radar in your browser.
  2. Open DevTools → Application → Cookies → copy all cookies as JSON.
  3. Store as TIKTOK_COOKIES environment variable in Railway.
  Without cookies the actor returns empty or errors out.

Target used: "Top Ads Dashboard" — supports keyword search + region filter.
Cost: ~$0.002 per item.

Region codes for MENA (pass as-is to actor):
  SA = Saudi Arabia, AE = UAE, EG = Egypt,
  KW = Kuwait, QA = Qatar, BH = Bahrain, OM = Oman, MA = Morocco
"""

import os
import requests
from typing import Iterator
from .base import AdSource, NormalizedAd


# Map our ISO-2 country codes to TikTok Creative Center region names.
# Run a test and inspect the Region dropdown to get the full list.
COUNTRY_TO_REGION = {
    "SA": "SA",
    "AE": "AE",
    "EG": "EG",
    "KW": "KW",
    "QA": "QA",
    "BH": "BH",
    "OM": "OM",
    "MA": "MA",
    "US": "US",
    "GB": "GB",
}


def _g(d: dict, *keys, default=""):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


class TikTokCCSource(AdSource):
    name = "tiktok_cc"

    def __init__(self, token: str, actor: str):
        if not token:
            raise ValueError("APIFY_TOKEN is empty.")
        self.cookies = os.environ.get("TIKTOK_COOKIES", "")
        if not self.cookies:
            print("[tiktok_cc] WARNING: TIKTOK_COOKIES not set — actor will likely fail.")
        self.url = (
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
            f"?token={token}"
        )

    def _map(self, raw: dict, country: str) -> NormalizedAd:
        ad_id = "tt_" + str(_g(raw, "id", "adId", "itemId", "material_id"))
        return NormalizedAd(
            ad_id=ad_id,
            page_id=str(_g(raw, "advertiserId", "brandId", "account_id")),
            page_name=_g(raw, "brandName", "advertiser", "brand",
                         "nickname", "author_name"),
            country=country,
            body=_g(raw, "adText", "caption", "text", "description",
                    "video_info.description"),
            title=_g(raw, "title", "objective", "ad_title"),
            description=_g(raw, "ctaText", "call_to_action", "cta_type"),
            platforms="tiktok",
            snapshot_url=_g(raw, "videoUrl", "cover", "video_cover_url",
                            "url", "share_url"),
            start_time=_g(raw, "firstSeen", "create_time", "publish_time",
                          default=None),
            stop_time=None,
            source=self.name,
            extra={
                "like_count": _g(raw, "likeCount", "like_count"),
                "industry":   _g(raw, "industry_key", "industry"),
            },
        )

    def fetch_ads(self, country, page_ids=None, search_terms=None,
                  limit=200) -> Iterator[NormalizedAd]:

        region = COUNTRY_TO_REGION.get(country, country)

        # Build one request per search term (or one generic request if no terms).
        queries = search_terms if search_terms else [None]

        for term in queries:
            actor_input = {
                "target": "Top Ads Dashboard",
                "cookies": self.cookies,
                # Top Ads Dashboard settings:
                "dashboard_search":  term or "",
                "dashboard_region":  region,
                "dashboard_period":  "Last 7 days",
                "dashboard_sort_by":  "For You",
                "limit":   min(limit, 50),   # actor default max per page
                "page":    1,
            }

            try:
                resp = requests.post(self.url, json=actor_input, timeout=600)
                resp.raise_for_status()
            except requests.HTTPError as e:
                print(f"[tiktok_cc] HTTP {e.response.status_code} "
                      f"({country}/{term}): {e.response.text[:150]}")
                continue
            except Exception as e:
                print(f"[tiktok_cc] request failed ({country}/{term}): {e}")
                continue

            items = resp.json()
            if not isinstance(items, list):
                print(f"[tiktok_cc] unexpected response: {type(items)}")
                continue

            for raw in items:
                ad = self._map(raw, country)
                if ad.ad_id != "tt_":
                    yield ad