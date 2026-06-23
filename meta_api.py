"""
Official Meta Ad Library API adapter (the /ads_archive Graph endpoint).

IMPORTANT coverage note (by design, not a bug):
  - Political/social/issue ads: returned worldwide.
  - Commercial ads: returned ONLY when delivered to the EU/UK.
  => Competitors that advertise ONLY inside MENA will return little or nothing.
     That is exactly why AdSource is pluggable: swap this for a paid provider
     later without touching the rest of the agent.
"""

import json
import time
import requests
from typing import Iterator

from .base import AdSource, NormalizedAd

# Commercial-safe fields (always available). EU-only fields like impressions/
# spend/demographics are intentionally omitted because they return null in MENA.
FIELDS = [
    "id",
    "page_id",
    "page_name",
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_descriptions",
    "ad_creative_link_captions",
    "publisher_platforms",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_snapshot_url",
    "languages",
]

# Graph API error codes that mean "you are rate limited / throttled".
RATE_LIMIT_CODES = {4, 17, 32, 613}


class MetaAdLibrarySource(AdSource):
    name = "meta_ad_library"

    def __init__(self, access_token: str, api_version: str = "v22.0", ad_type: str = "ALL"):
        if not access_token:
            raise ValueError("META_ACCESS_TOKEN is empty. Set it in your .env file.")
        self.access_token = access_token
        self.endpoint = f"https://graph.facebook.com/{api_version}/ads_archive"
        self.ad_type = ad_type

    def _first(self, value) -> str:
        """API returns some creative fields as lists; take the first item safely."""
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        return ""

    def fetch_ads(
        self,
        country: str,
        page_ids: list[str] | None = None,
        search_terms: list[str] | None = None,
        limit: int = 200,
    ) -> Iterator[NormalizedAd]:
        params = {
            "access_token": self.access_token,
            "ad_type": self.ad_type,
            "ad_reached_countries": json.dumps([country]),
            "fields": ",".join(FIELDS),
            "limit": min(limit, 250),
        }
        if page_ids:
            params["search_page_ids"] = json.dumps(page_ids)
        elif search_terms:
            # API takes a single search_terms string; we join with OR semantics.
            params["search_terms"] = " ".join(search_terms)
        else:
            raise ValueError("Provide either page_ids or search_terms.")

        url = self.endpoint
        first_request = True

        while url:
            resp = requests.get(url, params=params if first_request else None, timeout=30)
            first_request = False
            data = resp.json()

            if "error" in data:
                err = data["error"]
                code = err.get("code")
                if code in RATE_LIMIT_CODES:
                    print(f"[meta] rate limited (code {code}) — sleeping 60s")
                    time.sleep(60)
                    continue
                raise RuntimeError(f"Meta API error: {err}")

            for raw in data.get("data", []):
                yield NormalizedAd(
                    ad_id=str(raw.get("id", "")),
                    page_id=str(raw.get("page_id", "")),
                    page_name=raw.get("page_name", ""),
                    country=country,
                    body=self._first(raw.get("ad_creative_bodies")),
                    title=self._first(raw.get("ad_creative_link_titles")),
                    description=self._first(raw.get("ad_creative_link_descriptions")),
                    link_caption=self._first(raw.get("ad_creative_link_captions")),
                    platforms=",".join(raw.get("publisher_platforms", []) or []),
                    snapshot_url=raw.get("ad_snapshot_url", ""),
                    start_time=raw.get("ad_delivery_start_time"),
                    stop_time=raw.get("ad_delivery_stop_time"),
                    source=self.name,
                    extra={"languages": raw.get("languages", [])},
                )

            # Cursor pagination: follow paging.next (a full URL) until exhausted.
            url = data.get("paging", {}).get("next")
            time.sleep(1)  # be gentle on the hourly budget
