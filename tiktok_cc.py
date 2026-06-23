"""
TikTok Creative Center source (via Apify).

TikTok's Creative Center "Top Ads" is more openly accessible than Meta's
commercial API and is a strong second signal for MENA. Accessed here through an
Apify actor. Same caveat as Meta: adjust _map() to your chosen actor's schema.
"""

import requests
from typing import Iterator
from .base import AdSource, NormalizedAd
from .apify_meta import _g


class TikTokCCSource(AdSource):
    name = "tiktok_cc"

    def __init__(self, token: str, actor: str):
        if not token:
            raise ValueError("APIFY_TOKEN is empty.")
        self.url = (
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
            f"?token={token}"
        )

    def _map(self, raw: dict, country: str) -> NormalizedAd:
        return NormalizedAd(
            ad_id="tt_" + str(_g(raw, "id", "adId", "itemId")),
            page_id=str(_g(raw, "advertiserId", "brandId")),
            page_name=_g(raw, "brandName", "advertiser", "brand"),
            country=country,
            body=_g(raw, "adText", "caption", "text", "description"),
            title=_g(raw, "title", "objective"),
            description=_g(raw, "ctaText", "callToAction"),
            platforms="tiktok",
            snapshot_url=_g(raw, "videoUrl", "url", "coverUrl"),
            start_time=_g(raw, "firstSeen", "startDate", default=None),
            stop_time=_g(raw, "lastSeen", "endDate", default=None),
            source=self.name,
        )

    def fetch_ads(self, country, page_ids=None, search_terms=None,
                  limit=200) -> Iterator[NormalizedAd]:
        actor_input = {
            "region": country,
            "limit": limit,
            "period": 30,          # last 30 days top ads
            "orderBy": "ctr",
        }
        if search_terms:
            actor_input["keywords"] = search_terms

        resp = requests.post(self.url, json=actor_input, timeout=600)
        resp.raise_for_status()
        for raw in resp.json():
            ad = self._map(raw, country)
            if ad.ad_id != "tt_":
                yield ad
