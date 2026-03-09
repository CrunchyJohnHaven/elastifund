"""Environment-backed settings for digital-product niche research."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path


def _get_bool(name: str, default: bool) -> bool:
    raw = getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _get_text(name: str, default: str) -> str:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


@dataclass(frozen=True)
class DigitalProductResearchSettings:
    db_path: Path = Path("data/digital_products.db")
    export_dir: Path = Path("data/digital_product_exports")
    default_marketplace: str = "etsy"
    default_limit: int = 25
    embedding_dimensions: int = 768
    competition_floor: int = 1
    minimum_monthly_demand: float = 0.0
    minimum_average_price: float = 0.0
    minimum_audit_opportunity: float = 0.55
    minimum_icp_match_score: float = 0.55
    lead_list_per_niche: int = 3
    synthetic_leads_enabled: bool = True
    crm_sync_include_synthetic: bool = False
    elastic_index_name: str = "elastifund-knowledge"

    @classmethod
    def from_env(cls) -> "DigitalProductResearchSettings":
        return cls(
            db_path=Path(_get_text("JJ_DP_DB_PATH", "data/digital_products.db")),
            export_dir=Path(_get_text("JJ_DP_EXPORT_DIR", "data/digital_product_exports")),
            default_marketplace=_get_text("JJ_DP_MARKETPLACE", "etsy").lower(),
            default_limit=max(1, _get_int("JJ_DP_RESULT_LIMIT", 25)),
            embedding_dimensions=max(8, _get_int("JJ_DP_EMBEDDING_DIMS", 768)),
            competition_floor=max(1, _get_int("JJ_DP_COMPETITION_FLOOR", 1)),
            minimum_monthly_demand=max(0.0, _get_float("JJ_DP_MIN_MONTHLY_DEMAND", 0.0)),
            minimum_average_price=max(0.0, _get_float("JJ_DP_MIN_AVG_PRICE", 0.0)),
            minimum_audit_opportunity=max(0.0, min(1.0, _get_float("JJ_DP_MIN_AUDIT_OPPORTUNITY", 0.55))),
            minimum_icp_match_score=max(0.0, min(1.0, _get_float("JJ_DP_MIN_ICP_MATCH", 0.55))),
            lead_list_per_niche=max(1, _get_int("JJ_DP_LEADS_PER_NICHE", 3)),
            synthetic_leads_enabled=_get_bool("JJ_DP_SYNTHETIC_LEADS", True),
            crm_sync_include_synthetic=_get_bool("JJ_DP_CRM_SYNC_INCLUDE_SYNTHETIC", False),
            elastic_index_name=_get_text("JJ_DP_ELASTIC_INDEX", "elastifund-knowledge"),
        )

    def ensure_paths(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
