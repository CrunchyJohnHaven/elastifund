"""Initial schema — all 8 tables.

Revision ID: 001
Revises: None
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── markets ──
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("condition_id", sa.String(255)),
        sa.Column("question", sa.Text),
        sa.Column("slug", sa.String(500)),
        sa.Column("status", sa.String(50)),
        sa.Column("outcome_yes_price", sa.Float),
        sa.Column("outcome_no_price", sa.Float),
        sa.Column("volume", sa.Float),
        sa.Column("liquidity", sa.Float),
        sa.Column("clob_token_id_yes", sa.String(255)),
        sa.Column("clob_token_id_no", sa.String(255)),
        sa.Column("end_date", sa.String(50)),
        sa.Column("category", sa.String(100)),
        sa.Column("resolution", sa.String(10)),
        sa.Column("raw_payload", sa.JSON),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # ── orderbook_snapshots ──
    op.create_table(
        "orderbook_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(255), index=True, nullable=False),
        sa.Column("token_id", sa.String(255), index=True, nullable=False),
        sa.Column("side_label", sa.String(10)),
        sa.Column("best_bid", sa.Float),
        sa.Column("best_ask", sa.Float),
        sa.Column("spread", sa.Float),
        sa.Column("midpoint", sa.Float),
        sa.Column("bid_depth", sa.Integer, server_default="0"),
        sa.Column("ask_depth", sa.Integer, server_default="0"),
        sa.Column("raw_payload", sa.JSON),
        sa.Column("fetched_at", sa.DateTime, index=True, nullable=False),
    )
    op.create_index("ix_ob_token_ts", "orderbook_snapshots", ["token_id", "fetched_at"])

    # ── trade_ticks ──
    op.create_table(
        "trade_ticks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(255), index=True, nullable=False),
        sa.Column("token_id", sa.String(255), index=True, nullable=False),
        sa.Column("side_label", sa.String(10)),
        sa.Column("price", sa.Float),
        sa.Column("size", sa.Float),
        sa.Column("side", sa.String(10)),
        sa.Column("trade_ts", sa.String(50)),
        sa.Column("raw_payload", sa.JSON),
        sa.Column("fetched_at", sa.DateTime, index=True, nullable=False),
    )
    op.create_index("ix_tt_token_ts", "trade_ticks", ["token_id", "fetched_at"])

    # ── detector_runs ──
    op.create_table(
        "detector_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("status", sa.String(20), server_default="running"),
        sa.Column("markets_scanned", sa.Integer, server_default="0"),
        sa.Column("edges_found", sa.Integer, server_default="0"),
        sa.Column("opportunities_created", sa.Integer, server_default="0"),
        sa.Column("config", sa.JSON),
        sa.Column("error_detail", sa.Text),
    )

    # ── edge_cards ──
    op.create_table(
        "edge_cards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(255), index=True, nullable=False),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("detector_runs.id"), index=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("model_prob", sa.Float, nullable=False),
        sa.Column("market_price", sa.Float, nullable=False),
        sa.Column("edge", sa.Float, nullable=False),
        sa.Column("confidence", sa.String(20)),
        sa.Column("reasoning", sa.Text),
        sa.Column("raw_payload", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_ec_market_created", "edge_cards", ["market_id", "created_at"])

    # ── opportunities ──
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("edge_card_id", sa.Integer, sa.ForeignKey("edge_cards.id"), index=True),
        sa.Column("market_id", sa.String(255), index=True, nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("model_prob", sa.Float, nullable=False),
        sa.Column("edge", sa.Float, nullable=False),
        sa.Column("position_size", sa.Float, server_default="0.0"),
        sa.Column("status", sa.String(20), server_default="open"),
        sa.Column("outcome", sa.String(10)),
        sa.Column("pnl", sa.Float),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime),
    )

    # ── experiments ──
    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("hypothesis", sa.Text),
        sa.Column("parameters", sa.JSON),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("result_summary", sa.Text),
        sa.Column("result_data", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime),
    )

    # ── system_logs ──
    op.create_table(
        "system_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("component", sa.String(100), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("data", sa.JSON),
        sa.Column("created_at", sa.DateTime, index=True, nullable=False),
    )
    op.create_index("ix_syslog_level_ts", "system_logs", ["level", "created_at"])


def downgrade() -> None:
    op.drop_table("system_logs")
    op.drop_table("experiments")
    op.drop_table("opportunities")
    op.drop_table("edge_cards")
    op.drop_table("detector_runs")
    op.drop_table("trade_ticks")
    op.drop_table("orderbook_snapshots")
    op.drop_table("markets")
