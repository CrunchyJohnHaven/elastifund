"""Digital-product niche discovery for the non-trading lane."""

from .config import DigitalProductResearchSettings
from .models import DiscoveryResult, NicheCandidate, RankedNiche
from .research import NicheDiscoveryAgent, StaticMarketplaceSource
from .store import DigitalProductStore

__all__ = [
    "DigitalProductResearchSettings",
    "DigitalProductStore",
    "DiscoveryResult",
    "NicheCandidate",
    "NicheDiscoveryAgent",
    "RankedNiche",
    "StaticMarketplaceSource",
]
