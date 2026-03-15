"""Digital-product niche discovery for the non-trading lane."""

from .config import DigitalProductResearchSettings
from .models import CRMSyncSummary, DiscoveryResult, GeneratedLead, NicheCandidate, RankedNiche
from .research import NicheDiscoveryAgent, StaticMarketplaceSource
from .store import DigitalProductStore

__all__ = [
    "CRMSyncSummary",
    "DigitalProductResearchSettings",
    "DigitalProductStore",
    "DiscoveryResult",
    "GeneratedLead",
    "NicheCandidate",
    "NicheDiscoveryAgent",
    "RankedNiche",
    "StaticMarketplaceSource",
]
