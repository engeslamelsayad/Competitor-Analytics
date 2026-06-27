"""
TikTok Creative Center source — input schema verified from actual Apify run (June 2026).

Verified fields from actor test run:
  "target": "top_ads_dashboard"      ← lowercase underscore (NOT "Top Ads Dashboard")
  "dashboard_region": ["SA"]         ← array, not string
  "dashboard_search": "keyword"
  "dashboard_sort_by": "impression"
  "dashboard_period": "7"            ← string not int
  "dashboard_page": 1
  "dashboard_limit": 20
  "cookies": "..."                   ← required, from TIKTOK_COOKIES env var
"""

import os
import requests
from typing import Iterator
from .base import AdSource, NormalizedAd

COUNTRY_TO_REGION = {
    "SA": "SA", "AE": "AE", "EG": "EG",
    "KW": "KW", "QA": "QA", "BH": "BH",
    "OM": "OM", "MA": "MA",
    "LY": "LY", "PS": "PS", "LB": "LB",
    "SY": "SY", "JO": "JO", "IQ": "IQ",
    "TN": "TN",
}

def _g(d, *keys, default=""):
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
            print("[tiktok_cc] WARNING: TIKTOK_COOKIES not set — skipping TikTok.")
        self.url = (
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
            f"?token={token}"
        )

    def _map(self, raw: dict, country: str) -> NormalizedAd:
        ad_id = "tt_" + str(_g(raw, "id", "adId", "itemId", "material_id"))
        return NormalizedAd(
            ad_id=ad_id,
            page_id=str(_g(raw, "advertiserId", "brandId", "account_id")),
            page_name=_g(raw, "brandName", "advertiser", "brand", "nickname"),
            country=country,
            body=_g(raw, "adText", "caption", "text", "description"),
            title=_g(raw, "title", "objective", "ad_title"),
            description=_g(raw, "ctaText", "call_to_action", "cta_type"),
            platforms="tiktok",
            snapshot_url=_g(raw, "videoUrl", "cover", "video_cover_url", "share_url"),
            start_time=_g(raw, "firstSeen", "create_time", "publish_time", default=None),
            stop_time=None,
            source=self.name,
            extra={
                "like_count": _g(raw, "likeCount", "like_count"),
                "industry":   _g(raw, "industry_key", "industry"),
            },
        )

    def fetch_ads(self, country, page_ids=None, search_terms=None,
                  limit=200) -> Iterator[NormalizedAd]:
        if not self.cookies:
            return

        region = COUNTRY_TO_REGION.get(country, country)
        queries = search_terms if search_terms else [None]

        for term in queries:
            actor_input = {
                "cookies":            self.cookies,
                "target":             "top_ads_dashboard",   # ← verified lowercase
                "dashboard_region":   [region],              # ← array
                "dashboard_search":   term or "",
                "dashboard_sort_by":  "impression",          # ← verified field
                "dashboard_period":   "7",                   # ← string
                "dashboard_page":     1,
                "dashboard_limit":    min(limit, 20),        # actor max per page = 20
            }
            try:
                resp = requests.post(self.url, json=actor_input, timeout=600)
                resp.raise_for_status()
            except requests.HTTPError as e:
                print(f"[tiktok_cc] HTTP {e.response.status_code} ({country}/{term}): "
                      f"{e.response.text[:150]}")
                continue
            except Exception as e:
                print(f"[tiktok_cc] failed ({country}/{term}): {e}")
                continue

            items = resp.json()
            if not isinstance(items, list):
                continue
            for raw in items:
                ad = self._map(raw, country)
                if ad.ad_id != "tt_":
                    yield ad
