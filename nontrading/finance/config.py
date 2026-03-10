"""Environment-backed settings for the finance control plane."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from os import getenv
from pathlib import Path
from typing import Any

VALID_AUTONOMY_MODES = ("shadow", "live_spend", "live_treasury")
VALID_EQUITY_TREATMENTS = ("illiquid_only",)


def _get_text(name: str, default: str) -> str:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _get_float(name: str, default: float) -> float:
    raw = getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _normalize_whitelist_value(item: Any) -> str:
    if isinstance(item, str):
        return item.strip().lower()
    if isinstance(item, dict):
        for key in ("destination", "destination_id", "account", "account_id", "name"):
            value = item.get(key)
            if value:
                return str(value).strip().lower()
    return ""


def parse_whitelist(raw: str) -> tuple[str, ...]:
    text = raw.strip()
    if not text:
        return ()
    payload_text = text
    maybe_path = Path(text)
    if maybe_path.exists():
        payload_text = maybe_path.read_text(encoding="utf-8")
    data = json.loads(payload_text)
    if isinstance(data, dict):
        items = data.get("destinations", data.get("whitelist", []))
    elif isinstance(data, list):
        items = data
    else:
        items = []
    normalized = tuple(
        value
        for value in (_normalize_whitelist_value(item) for item in items)
        if value
    )
    return tuple(dict.fromkeys(normalized))


@dataclass(frozen=True)
class FinanceSettings:
    db_path: Path = Path("state/jj_finance.db")
    autonomy_mode: str = "shadow"
    single_action_cap_usd: float = 250.0
    monthly_new_commitment_cap_usd: float = 1000.0
    min_cash_reserve_months: float = 1.0
    equity_treatment: str = "illiquid_only"
    whitelist_json: str = "[]"
    imports_dir: Path = Path("data/finance_imports")
    reports_dir: Path = Path("reports/finance")
    workspace_root: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path))
        object.__setattr__(self, "imports_dir", Path(self.imports_dir))
        object.__setattr__(self, "reports_dir", Path(self.reports_dir))
        object.__setattr__(self, "workspace_root", Path(self.workspace_root))

    @classmethod
    def from_env(cls) -> "FinanceSettings":
        return cls(
            db_path=Path(_get_text("JJ_FINANCE_DB_PATH", "state/jj_finance.db")),
            autonomy_mode=_get_text("JJ_FINANCE_AUTONOMY_MODE", "shadow").lower(),
            single_action_cap_usd=_get_float("JJ_FINANCE_SINGLE_ACTION_CAP_USD", 250.0),
            monthly_new_commitment_cap_usd=_get_float("JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD", 1000.0),
            min_cash_reserve_months=_get_float("JJ_FINANCE_MIN_CASH_RESERVE_MONTHS", 1.0),
            equity_treatment=_get_text("JJ_FINANCE_EQUITY_TREATMENT", "illiquid_only").lower(),
            whitelist_json=_get_text("JJ_FINANCE_WHITELIST_JSON", "[]"),
            imports_dir=Path(_get_text("JJ_FINANCE_IMPORTS_DIR", "data/finance_imports")),
            reports_dir=Path(_get_text("JJ_FINANCE_REPORTS_DIR", "reports/finance")),
            workspace_root=Path(_get_text("JJ_FINANCE_WORKSPACE_ROOT", str(Path.cwd()))),
        )

    def ensure_paths(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.imports_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    @property
    def whitelist(self) -> tuple[str, ...]:
        return parse_whitelist(self.whitelist_json)

    @property
    def latest_report_path(self) -> Path:
        return self.reports_dir / "latest.json"

    @property
    def subscription_audit_path(self) -> Path:
        return self.reports_dir / "subscription_audit.json"

    @property
    def allocation_plan_path(self) -> Path:
        return self.reports_dir / "allocation_plan.json"

    @property
    def action_queue_path(self) -> Path:
        return self.reports_dir / "action_queue.json"

    def with_workspace(self, workspace_root: str | Path) -> "FinanceSettings":
        return FinanceSettings(
            db_path=self.db_path,
            autonomy_mode=self.autonomy_mode,
            single_action_cap_usd=self.single_action_cap_usd,
            monthly_new_commitment_cap_usd=self.monthly_new_commitment_cap_usd,
            min_cash_reserve_months=self.min_cash_reserve_months,
            equity_treatment=self.equity_treatment,
            whitelist_json=self.whitelist_json,
            imports_dir=self.imports_dir,
            reports_dir=self.reports_dir,
            workspace_root=Path(workspace_root),
        )

    def validate(self) -> None:
        if self.autonomy_mode not in VALID_AUTONOMY_MODES:
            raise ValueError(f"Unsupported finance autonomy mode: {self.autonomy_mode}")
        if self.equity_treatment not in VALID_EQUITY_TREATMENTS:
            raise ValueError(f"Unsupported finance equity treatment: {self.equity_treatment}")
