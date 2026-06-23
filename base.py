"""
Abstract data-source interface.

The whole point: the rest of the agent (storage, classification, analysis,
reporting) NEVER talks to a specific provider. It only talks to this interface.

To add a paid third-party provider later, you write ONE new class that
subclasses AdSource and implements fetch_ads(). Nothing else changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Iterator, Optional


@dataclass
class NormalizedAd:
    """A single ad in a provider-agnostic shape."""
    ad_id: str
    page_id: str
    page_name: str
    country: str
    body: str = ""
    title: str = ""
    description: str = ""
    link_caption: str = ""
    platforms: str = ""            # comma-joined, e.g. "facebook,instagram"
    snapshot_url: str = ""
    start_time: Optional[str] = None
    stop_time: Optional[str] = None
    source: str = "unknown"        # which adapter produced this
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return d


class AdSource(ABC):
    """Base class every data source must implement."""

    name: str = "base"

    @abstractmethod
    def fetch_ads(
        self,
        country: str,
        page_ids: list[str] | None = None,
        search_terms: list[str] | None = None,
        limit: int = 200,
    ) -> Iterator[NormalizedAd]:
        """Yield NormalizedAd objects for the given country + targets."""
        raise NotImplementedError
