"""Market data ingestion layer for Polymarket.

Read-only module that fetches and stores:
- Market metadata from Gamma API
- Order book snapshots from CLOB API
- Recent trades from CLOB API
"""

from src.data.ingest.fetcher import MarketDataFetcher

__all__ = ["MarketDataFetcher"]
