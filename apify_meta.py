"""
Apify-based Meta Ad Library source.

This is the path that actually covers MENA commercial ads: instead of the
official API (EU/UK-only for commercial), it runs an Apify actor that scrapes the
public Ad Library web UI.

NOTE: Field names differ between actors on the Apify Store. This mapper is
defensive (tries several common keys). Pick an actor, run it once, and adjust
_map() to its exact output if needed.
NOTE: scraping the public UI is a grey area under Meta's ToS — Apify runs it on
their infrastructure; decide what's acceptable for your business.
"""

import requests
from typing import Iterator
from .base import AdSource, NormalizedAd


def _g(d: dict, *keys, default=""):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


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

    def _map(self, raw: dict, country: str) -> NormalizedAd:
        return NormalizedAd(
            ad_id=str(_g(raw, "adArchiveID", "ad_archive_id", "id")),
            page_id=str(_g(raw, "pageID", "page_id")),
            page_name=_g(raw, "pageName", "page_name", "advertiser"),
            country=country,
            body=_g(raw, "body", "adText", "ad_creative_body", "text"),
            title=_g(raw, "title", "ad_creative_link_title", "linkTitle"),
            description=_g(raw, "linkDescription", "ad_creative_link_description"),
            link_caption=_g(raw, "caption", "linkCaption"),
            platforms=",".join(_g(raw, "publisherPlatform", "platforms", default=[]) or []),
            snapshot_url=_g(raw, "snapshotUrl", "ad_snapshot_url", "url"),
            start_time=_g(raw, "startDate", "ad_delivery_start_time", default=None),
            stop_time=_g(raw, "endDate", "ad_delivery_stop_time", default=None),
            source=self.name,
        )

    def fetch_ads(self, country, page_ids=None, search_terms=None,
                  limit=200) -> Iterator[NormalizedAd]:
        # Actor input schema varies; this covers the common shape. Adjust per actor.
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
            ad = self._map(raw, country)
            if ad.ad_id:
                yield ad
