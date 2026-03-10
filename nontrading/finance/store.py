"""SQLite store for the finance control plane."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from nontrading.finance.models import (
    FinanceAccount,
    FinanceAction,
    FinanceExperiment,
    FinancePosition,
    FinanceRecurringCommitment,
    FinanceSubscription,
    FinanceTransaction,
    utc_now,
)


class FinanceStore:
    """Synchronous SQLite store for finance state and queued actions."""

    def __init__(self, db_path: str | Path, settings: Any | None = None):
        self.db_path = Path(db_path)
        self.settings = settings
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS finance_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    institution TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT 'USD',
                    balance_usd REAL NOT NULL DEFAULT 0.0,
                    available_cash_usd REAL NOT NULL DEFAULT 0.0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finance_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_key TEXT NOT NULL UNIQUE,
                    account_key TEXT NOT NULL,
                    posted_at TEXT NOT NULL,
                    merchant TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    amount_usd REAL NOT NULL DEFAULT 0.0,
                    category TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_finance_transactions_merchant
                    ON finance_transactions(merchant, posted_at);

                CREATE TABLE IF NOT EXISTS finance_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_key TEXT NOT NULL UNIQUE,
                    account_key TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    asset_type TEXT NOT NULL DEFAULT 'security',
                    quantity REAL NOT NULL DEFAULT 0.0,
                    market_value_usd REAL NOT NULL DEFAULT 0.0,
                    deployable_cash_usd REAL NOT NULL DEFAULT 0.0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finance_recurring_commitments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commitment_key TEXT NOT NULL UNIQUE,
                    vendor TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    amount_usd REAL NOT NULL DEFAULT 0.0,
                    monthly_cost_usd REAL NOT NULL DEFAULT 0.0,
                    cadence TEXT NOT NULL DEFAULT 'monthly',
                    essential INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finance_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_key TEXT NOT NULL UNIQUE,
                    vendor TEXT NOT NULL,
                    product_name TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    monthly_cost_usd REAL NOT NULL DEFAULT 0.0,
                    billing_cycle TEXT NOT NULL DEFAULT 'monthly',
                    usage_frequency TEXT NOT NULL DEFAULT 'unknown',
                    status TEXT NOT NULL DEFAULT 'active',
                    duplicate_group TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_finance_subscriptions_status
                    ON finance_subscriptions(status, category);

                CREATE TABLE IF NOT EXISTS finance_budget_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_name TEXT NOT NULL UNIQUE,
                    value_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finance_experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    bucket TEXT NOT NULL DEFAULT 'buy_tool_or_data',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    budget_usd REAL NOT NULL DEFAULT 0.0,
                    monthly_budget_usd REAL NOT NULL DEFAULT 0.0,
                    expected_net_value_30d REAL NOT NULL DEFAULT 0.0,
                    expected_information_gain_30d REAL NOT NULL DEFAULT 0.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finance_action_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_key TEXT NOT NULL UNIQUE,
                    action_type TEXT NOT NULL,
                    bucket TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    amount_usd REAL NOT NULL DEFAULT 0.0,
                    monthly_commitment_usd REAL NOT NULL DEFAULT 0.0,
                    priority_score REAL NOT NULL DEFAULT 0.0,
                    destination TEXT NOT NULL DEFAULT '',
                    vendor TEXT NOT NULL DEFAULT '',
                    mode_requested TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    rollback TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    cooldown_until TEXT,
                    requires_whitelist INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    executed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_finance_action_queue_status
                    ON finance_action_queue(status, updated_at);

                CREATE TABLE IF NOT EXISTS finance_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_type TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_finance_snapshots_type
                    ON finance_snapshots(snapshot_type, created_at);
                """
            )

    def _upsert_record(self, table: str, unique_key: str, key_value: str, payload: dict[str, Any], columns: Iterable[str]) -> int:
        now = utc_now()
        insert_columns = list(columns) + ["created_at", "updated_at"]
        update_columns = [column for column in columns if column != unique_key]
        placeholders = ", ".join("?" for _ in insert_columns)
        sql = (
            f"INSERT INTO {table} ({', '.join(insert_columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({unique_key}) DO UPDATE SET "
            + ", ".join(f"{column} = excluded.{column}" for column in update_columns)
            + ", updated_at = excluded.updated_at"
        )
        values = [payload[column] for column in columns] + [now, now]
        with self._connect() as conn:
            conn.execute(sql, values)
            row = conn.execute(f"SELECT id FROM {table} WHERE {unique_key} = ?", (key_value,)).fetchone()
        if row is None:
            raise RuntimeError(f"Missing row after upsert into {table}: {key_value}")
        return int(row["id"])

    def _row_to_account(self, row: sqlite3.Row) -> FinanceAccount:
        metadata = json.loads(row["metadata_json"])
        return FinanceAccount(
            id=row["id"],
            account_key=row["account_key"],
            name=row["name"],
            account_type=row["account_type"],
            institution=row["institution"],
            currency=row["currency"],
            balance_usd=float(row["balance_usd"]),
            current_balance_usd=float(row["balance_usd"]),
            available_cash_usd=float(row["available_cash_usd"]),
            source=row["source"],
            liquidity_tier=str(metadata.get("liquidity_tier", "liquid")),
            source_type=str(metadata.get("source_type", row["source"])),
            source_ref=str(metadata.get("source_ref", "")),
            external_id=str(metadata.get("external_id", row["account_key"])),
            metadata=metadata,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_transaction(self, row: sqlite3.Row) -> FinanceTransaction:
        metadata = json.loads(row["metadata_json"])
        return FinanceTransaction(
            id=row["id"],
            transaction_key=row["transaction_key"],
            account_key=row["account_key"],
            posted_at=row["posted_at"],
            merchant=row["merchant"],
            description=row["description"],
            amount_usd=float(row["amount_usd"]),
            category=row["category"],
            source=row["source"],
            transaction_id=str(metadata.get("transaction_id", row["transaction_key"])),
            direction=str(metadata.get("direction", "deposit" if float(row["amount_usd"]) > 0 else "withdrawal")),
            metadata=metadata,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_position(self, row: sqlite3.Row) -> FinancePosition:
        metadata = json.loads(row["metadata_json"])
        return FinancePosition(
            id=row["id"],
            position_key=row["position_key"],
            account_key=row["account_key"],
            symbol=row["symbol"],
            name=str(metadata.get("name", row["symbol"])),
            asset_type=row["asset_type"],
            asset_class=str(metadata.get("asset_class", row["asset_type"])),
            quantity=float(row["quantity"]),
            cost_basis_usd=float(metadata.get("cost_basis_usd", 0.0) or 0.0),
            market_value_usd=float(row["market_value_usd"]),
            deployable_cash_usd=float(row["deployable_cash_usd"]),
            source=row["source"],
            source_type=str(metadata.get("source_type", row["source"])),
            source_ref=str(metadata.get("source_ref", "")),
            external_id=str(metadata.get("external_id", row["position_key"])),
            liquidity_tier=str(metadata.get("liquidity_tier", "liquid")),
            metadata=metadata,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_commitment(self, row: sqlite3.Row) -> FinanceRecurringCommitment:
        return FinanceRecurringCommitment(
            id=row["id"],
            commitment_key=row["commitment_key"],
            vendor=row["vendor"],
            category=row["category"],
            amount_usd=float(row["amount_usd"]),
            monthly_cost_usd=float(row["monthly_cost_usd"]),
            cadence=row["cadence"],
            essential=bool(row["essential"]),
            source=row["source"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_subscription(self, row: sqlite3.Row) -> FinanceSubscription:
        return FinanceSubscription(
            id=row["id"],
            subscription_key=row["subscription_key"],
            vendor=row["vendor"],
            product_name=row["product_name"],
            category=row["category"],
            monthly_cost_usd=float(row["monthly_cost_usd"]),
            billing_cycle=row["billing_cycle"],
            usage_frequency=row["usage_frequency"],
            status=row["status"],
            duplicate_group=row["duplicate_group"],
            source=row["source"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_experiment(self, row: sqlite3.Row) -> FinanceExperiment:
        return FinanceExperiment(
            id=row["id"],
            experiment_key=row["experiment_key"],
            name=row["name"],
            bucket=row["bucket"],
            status=row["status"],
            budget_usd=float(row["budget_usd"]),
            monthly_budget_usd=float(row["monthly_budget_usd"]),
            expected_net_value_30d=float(row["expected_net_value_30d"]),
            expected_information_gain_30d=float(row["expected_information_gain_30d"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_action(self, row: sqlite3.Row) -> FinanceAction:
        return FinanceAction(
            id=row["id"],
            action_key=row["action_key"],
            action_type=row["action_type"],
            bucket=row["bucket"],
            title=row["title"],
            status=row["status"],
            amount_usd=float(row["amount_usd"]),
            monthly_commitment_usd=float(row["monthly_commitment_usd"]),
            priority_score=float(row["priority_score"]),
            destination=row["destination"],
            vendor=row["vendor"],
            mode_requested=row["mode_requested"],
            reason=row["reason"],
            rollback=row["rollback"],
            idempotency_key=row["idempotency_key"],
            cooldown_until=row["cooldown_until"],
            requires_whitelist=bool(row["requires_whitelist"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            executed_at=row["executed_at"],
        )

    def upsert_account(self, account: FinanceAccount) -> FinanceAccount:
        metadata = {
            **account.metadata,
            "external_id": account.external_id,
            "liquidity_tier": account.liquidity_tier,
            "source_type": account.source_type,
            "source_ref": account.source_ref,
        }
        payload = {
            "account_key": account.account_key,
            "name": account.name,
            "account_type": account.account_type,
            "institution": account.institution,
            "currency": account.currency,
            "balance_usd": account.current_balance_usd,
            "available_cash_usd": account.available_cash_usd,
            "source": account.source,
            "metadata_json": json.dumps(metadata, sort_keys=True),
        }
        record_id = self._upsert_record(
            "finance_accounts",
            "account_key",
            account.account_key,
            payload,
            (
                "account_key",
                "name",
                "account_type",
                "institution",
                "currency",
                "balance_usd",
                "available_cash_usd",
                "source",
                "metadata_json",
            ),
        )
        return FinanceAccount(**{**account.__dict__, "id": record_id})

    def upsert_transaction(self, transaction: FinanceTransaction) -> FinanceTransaction:
        metadata = {
            **transaction.metadata,
            "transaction_id": transaction.transaction_id,
            "direction": transaction.direction,
        }
        payload = {
            "transaction_key": transaction.transaction_key,
            "account_key": transaction.account_key,
            "posted_at": transaction.posted_at,
            "merchant": transaction.merchant,
            "description": transaction.description,
            "amount_usd": transaction.amount_usd,
            "category": transaction.category,
            "source": transaction.source,
            "metadata_json": json.dumps(metadata, sort_keys=True),
        }
        record_id = self._upsert_record(
            "finance_transactions",
            "transaction_key",
            transaction.transaction_key,
            payload,
            (
                "transaction_key",
                "account_key",
                "posted_at",
                "merchant",
                "description",
                "amount_usd",
                "category",
                "source",
                "metadata_json",
            ),
        )
        return FinanceTransaction(**{**transaction.__dict__, "id": record_id})

    def upsert_position(self, position: FinancePosition) -> FinancePosition:
        metadata = {
            **position.metadata,
            "name": position.name or position.symbol,
            "asset_class": position.asset_class or position.asset_type,
            "cost_basis_usd": position.cost_basis_usd,
            "external_id": position.external_id,
            "liquidity_tier": position.liquidity_tier,
            "source_type": position.source_type,
            "source_ref": position.source_ref,
        }
        payload = {
            "position_key": position.position_key,
            "account_key": position.account_key,
            "symbol": position.symbol,
            "asset_type": position.asset_type,
            "quantity": position.quantity,
            "market_value_usd": position.market_value_usd,
            "deployable_cash_usd": position.deployable_cash_usd,
            "source": position.source,
            "metadata_json": json.dumps(metadata, sort_keys=True),
        }
        record_id = self._upsert_record(
            "finance_positions",
            "position_key",
            position.position_key,
            payload,
            (
                "position_key",
                "account_key",
                "symbol",
                "asset_type",
                "quantity",
                "market_value_usd",
                "deployable_cash_usd",
                "source",
                "metadata_json",
            ),
        )
        return FinancePosition(**{**position.__dict__, "id": record_id})

    def upsert_recurring_commitment(self, commitment: FinanceRecurringCommitment) -> FinanceRecurringCommitment:
        payload = {
            "commitment_key": commitment.commitment_key,
            "vendor": commitment.vendor,
            "category": commitment.category,
            "amount_usd": commitment.amount_usd,
            "monthly_cost_usd": commitment.monthly_cost_usd,
            "cadence": commitment.cadence,
            "essential": 1 if commitment.essential else 0,
            "source": commitment.source,
            "metadata_json": json.dumps(commitment.metadata, sort_keys=True),
        }
        record_id = self._upsert_record(
            "finance_recurring_commitments",
            "commitment_key",
            commitment.commitment_key,
            payload,
            (
                "commitment_key",
                "vendor",
                "category",
                "amount_usd",
                "monthly_cost_usd",
                "cadence",
                "essential",
                "source",
                "metadata_json",
            ),
        )
        return FinanceRecurringCommitment(**{**commitment.__dict__, "id": record_id})

    def upsert_subscription(self, subscription: FinanceSubscription) -> FinanceSubscription:
        payload = {
            "subscription_key": subscription.subscription_key,
            "vendor": subscription.vendor,
            "product_name": subscription.product_name,
            "category": subscription.category,
            "monthly_cost_usd": subscription.monthly_cost_usd,
            "billing_cycle": subscription.billing_cycle,
            "usage_frequency": subscription.usage_frequency,
            "status": subscription.status,
            "duplicate_group": subscription.duplicate_group,
            "source": subscription.source,
            "metadata_json": json.dumps(subscription.metadata, sort_keys=True),
        }
        record_id = self._upsert_record(
            "finance_subscriptions",
            "subscription_key",
            subscription.subscription_key,
            payload,
            (
                "subscription_key",
                "vendor",
                "product_name",
                "category",
                "monthly_cost_usd",
                "billing_cycle",
                "usage_frequency",
                "status",
                "duplicate_group",
                "source",
                "metadata_json",
            ),
        )
        return FinanceSubscription(**{**subscription.__dict__, "id": record_id})

    def upsert_experiment(self, experiment: FinanceExperiment) -> FinanceExperiment:
        payload = {
            "experiment_key": experiment.experiment_key,
            "name": experiment.name,
            "bucket": experiment.bucket,
            "status": experiment.status,
            "budget_usd": experiment.budget_usd,
            "monthly_budget_usd": experiment.monthly_budget_usd,
            "expected_net_value_30d": experiment.expected_net_value_30d,
            "expected_information_gain_30d": experiment.expected_information_gain_30d,
            "metadata_json": json.dumps(experiment.metadata, sort_keys=True),
        }
        record_id = self._upsert_record(
            "finance_experiments",
            "experiment_key",
            experiment.experiment_key,
            payload,
            (
                "experiment_key",
                "name",
                "bucket",
                "status",
                "budget_usd",
                "monthly_budget_usd",
                "expected_net_value_30d",
                "expected_information_gain_30d",
                "metadata_json",
            ),
        )
        return FinanceExperiment(**{**experiment.__dict__, "id": record_id})

    def upsert_action(self, action: FinanceAction) -> FinanceAction:
        payload = {
            "action_key": action.action_key,
            "action_type": action.action_type,
            "bucket": action.bucket,
            "title": action.title,
            "status": action.status,
            "amount_usd": action.amount_usd,
            "monthly_commitment_usd": action.monthly_commitment_usd,
            "priority_score": action.priority_score,
            "destination": action.destination,
            "vendor": action.vendor,
            "mode_requested": action.mode_requested,
            "reason": action.reason,
            "rollback": action.rollback,
            "idempotency_key": action.idempotency_key,
            "cooldown_until": action.cooldown_until,
            "requires_whitelist": 1 if action.requires_whitelist else 0,
            "metadata_json": json.dumps(action.metadata, sort_keys=True),
            "executed_at": action.executed_at,
        }
        now = utc_now()
        sql = """
            INSERT INTO finance_action_queue (
                action_key,
                action_type,
                bucket,
                title,
                status,
                amount_usd,
                monthly_commitment_usd,
                priority_score,
                destination,
                vendor,
                mode_requested,
                reason,
                rollback,
                idempotency_key,
                cooldown_until,
                requires_whitelist,
                metadata_json,
                created_at,
                updated_at,
                executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(action_key) DO UPDATE SET
                action_type = excluded.action_type,
                bucket = excluded.bucket,
                title = excluded.title,
                status = excluded.status,
                amount_usd = excluded.amount_usd,
                monthly_commitment_usd = excluded.monthly_commitment_usd,
                priority_score = excluded.priority_score,
                destination = excluded.destination,
                vendor = excluded.vendor,
                mode_requested = excluded.mode_requested,
                reason = excluded.reason,
                rollback = excluded.rollback,
                idempotency_key = excluded.idempotency_key,
                cooldown_until = excluded.cooldown_until,
                requires_whitelist = excluded.requires_whitelist,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at,
                executed_at = excluded.executed_at
        """
        values = (
            payload["action_key"],
            payload["action_type"],
            payload["bucket"],
            payload["title"],
            payload["status"],
            payload["amount_usd"],
            payload["monthly_commitment_usd"],
            payload["priority_score"],
            payload["destination"],
            payload["vendor"],
            payload["mode_requested"],
            payload["reason"],
            payload["rollback"],
            payload["idempotency_key"],
            payload["cooldown_until"],
            payload["requires_whitelist"],
            payload["metadata_json"],
            now,
            now,
            payload["executed_at"],
        )
        with self._connect() as conn:
            conn.execute(sql, values)
            row = conn.execute(
                "SELECT * FROM finance_action_queue WHERE action_key = ?",
                (action.action_key,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"Missing action after upsert: {action.action_key}")
        return self._row_to_action(row)

    def upsert_accounts(self, accounts: Iterable[FinanceAccount]) -> list[FinanceAccount]:
        return [self.upsert_account(account) for account in accounts]

    def upsert_positions(self, positions: Iterable[FinancePosition]) -> list[FinancePosition]:
        return [self.upsert_position(position) for position in positions]

    def set_budget_policy(self, policy_name: str, value: Any) -> None:
        now = utc_now()
        payload_text = json.dumps(value, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO finance_budget_policies (policy_name, value_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(policy_name) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (policy_name, payload_text, now, now),
            )

    def get_budget_policy(self, policy_name: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM finance_budget_policies WHERE policy_name = ?",
                (policy_name,),
            ).fetchone()
        if row is None:
            return default
        return json.loads(row["value_json"])

    def list_accounts(self) -> list[FinanceAccount]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM finance_accounts ORDER BY name ASC").fetchall()
        return [self._row_to_account(row) for row in rows]

    def list_transactions(self) -> list[FinanceTransaction]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM finance_transactions ORDER BY posted_at ASC, id ASC").fetchall()
        return [self._row_to_transaction(row) for row in rows]

    def list_positions(self) -> list[FinancePosition]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM finance_positions ORDER BY asset_type ASC, symbol ASC").fetchall()
        return [self._row_to_position(row) for row in rows]

    def list_recurring_commitments(self) -> list[FinanceRecurringCommitment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM finance_recurring_commitments ORDER BY monthly_cost_usd DESC, vendor ASC"
            ).fetchall()
        return [self._row_to_commitment(row) for row in rows]

    def list_subscriptions(self) -> list[FinanceSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM finance_subscriptions ORDER BY monthly_cost_usd DESC, vendor ASC"
            ).fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def list_experiments(self) -> list[FinanceExperiment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM finance_experiments ORDER BY expected_net_value_30d DESC, expected_information_gain_30d DESC"
            ).fetchall()
        return [self._row_to_experiment(row) for row in rows]

    def get_action(self, action_key: str) -> FinanceAction | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM finance_action_queue WHERE action_key = ?",
                (action_key,),
            ).fetchone()
        return self._row_to_action(row) if row is not None else None

    def get_action_by_idempotency_key(self, idempotency_key: str) -> FinanceAction | None:
        if not idempotency_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM finance_action_queue
                WHERE idempotency_key = ?
                  AND status IN ('executed', 'simulated')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
        return self._row_to_action(row) if row is not None else None

    def list_actions(self, statuses: Iterable[str] | None = None) -> list[FinanceAction]:
        sql = "SELECT * FROM finance_action_queue"
        params: list[Any] = []
        if statuses:
            normalized = tuple(str(item) for item in statuses)
            placeholders = ", ".join("?" for _ in normalized)
            sql += f" WHERE status IN ({placeholders})"
            params.extend(normalized)
        sql += " ORDER BY priority_score DESC, created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_action(row) for row in rows]

    def record_snapshot(self, snapshot_type: str, schema_version: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO finance_snapshots (snapshot_type, schema_version, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (snapshot_type, schema_version, json.dumps(payload, sort_keys=True), utc_now()),
            )

    def latest_snapshot(self, snapshot_type: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT payload_json FROM finance_snapshots"
        params: list[Any] = []
        if snapshot_type:
            sql += " WHERE snapshot_type = ?"
            params.append(snapshot_type)
        sql += " ORDER BY id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def current_month_new_commitments_usd(self) -> float:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(monthly_commitment_usd), 0.0) AS total
                FROM finance_action_queue
                WHERE status = 'executed'
                  AND executed_at IS NOT NULL
                  AND substr(executed_at, 1, 7) = substr(?, 1, 7)
                """,
                (utc_now(),),
            ).fetchone()
        return round(float(row["total"] if row is not None else 0.0), 2)

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "accounts": len(self.list_accounts()),
            "transactions": len(self.list_transactions()),
            "positions": len(self.list_positions()),
            "recurring_commitments": len(self.list_recurring_commitments()),
            "subscriptions": len(self.list_subscriptions()),
            "experiments": len(self.list_experiments()),
            "actions": len(self.list_actions()),
        }

    def build_snapshot(self, settings: Any | None = None) -> Any:
        active_settings = settings or self.settings
        accounts = self.list_accounts()
        positions = self.list_positions()
        transactions = self.list_transactions()
        liquid_accounts = [account for account in accounts if account.liquidity_tier != "illiquid"]
        illiquid_positions = [position for position in positions if position.liquidity_tier == "illiquid"]
        deployable_cash_usd = round(sum(account.available_cash_usd for account in liquid_accounts), 6)
        illiquid_position_value_usd = round(sum(position.market_value_usd for position in illiquid_positions), 6)
        total_net_worth_proxy_usd = round(
            sum(account.current_balance_usd or 0.0 for account in accounts)
            + sum(
                position.market_value_usd
                for position in positions
                if position.asset_class not in {"startup_equity", "trading_position"}
            ),
            6,
        )
        summary = {
            "counts": {
                "accounts": len(accounts),
                "positions": len(positions),
                "transactions": len(transactions),
                "budget_policies": self.count_budget_policies(),
            },
            "totals": {
                "deployable_cash_usd": deployable_cash_usd,
                "illiquid_position_value_usd": illiquid_position_value_usd,
                "total_net_worth_proxy_usd": total_net_worth_proxy_usd,
            },
            "accounts": [
                {
                    "account_key": account.account_key,
                    "name": account.name,
                    "institution": account.institution,
                    "available_cash_usd": account.available_cash_usd,
                    "current_balance_usd": account.current_balance_usd,
                    "liquidity_tier": account.liquidity_tier,
                }
                for account in accounts
            ],
            "positions": [
                {
                    "position_key": position.position_key,
                    "name": position.name or position.symbol,
                    "market_value_usd": position.market_value_usd,
                    "liquidity_tier": position.liquidity_tier,
                }
                for position in positions
            ],
            "gaps": [],
        }

        class SnapshotArtifact:
            def __init__(self, summary: dict[str, Any]):
                self.summary = summary

        return SnapshotArtifact(summary)

    def count_budget_policies(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM finance_budget_policies").fetchone()
        return int(row["total"]) if row is not None else 0
