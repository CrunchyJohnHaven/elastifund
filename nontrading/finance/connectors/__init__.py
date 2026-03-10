"""Connector entrypoints for finance truth sync."""

from __future__ import annotations

from pathlib import Path

from nontrading.finance.config import FinanceSettings
from nontrading.finance.models import FinanceImportBundle

from .bank_import import load_bank_folder_bundle
from .positions_csv import load_positions_csv_bundle
from .startup_equity import load_startup_equity_bundle
from .trading_runtime import load_trading_runtime_bundle


def collect_default_bundles(
    settings: FinanceSettings,
    *,
    repo_root: str | Path,
    observed_at: str | None = None,
) -> tuple[FinanceImportBundle, ...]:
    imports_dir = Path(settings.imports_dir)
    return (
        load_bank_folder_bundle(imports_dir / "bank", observed_at=observed_at),
        load_positions_csv_bundle(imports_dir / "brokerage", observed_at=observed_at),
        load_startup_equity_bundle(imports_dir / "startup_equity.json", observed_at=observed_at),
        load_trading_runtime_bundle(repo_root, observed_at=observed_at),
    )


__all__ = [
    "collect_default_bundles",
    "load_bank_folder_bundle",
    "load_positions_csv_bundle",
    "load_startup_equity_bundle",
    "load_trading_runtime_bundle",
]
