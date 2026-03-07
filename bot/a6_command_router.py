#!/usr/bin/env python3
"""Routes A6OrderCommand objects to live ClobClient order submission.

This module bridges the A6BasketExecutor (pure state machine) to the
Polymarket CLOB API.  Each A6OrderCommand is converted into the appropriate
ClobClient call (PLACE, CANCEL, REPLACE, ROLLBACK).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("a6_command_router")


@dataclass(frozen=True)
class A6OrderResult:
    """Outcome of a single order API call."""

    command_action: str
    basket_id: str
    leg_id: str
    market_id: str
    token_id: str
    order_id: str
    success: bool
    error: str | None = None
    raw_response: dict | None = None


@dataclass(frozen=True)
class A6FillStatus:
    """Fill status for a single order polled from the CLOB."""

    order_id: str
    original_size: float
    size_matched: float
    remaining: float
    status: str  # "live", "matched", "cancelled", "expired"
    avg_price: float


class A6CommandRouter:
    """Converts A6OrderCommand objects into live ClobClient API calls.

    The router does NOT import py_clob_client types at module level;
    instead they are passed in at construction or via execute_commands().
    This keeps the module importable without py_clob_client installed.
    """

    def __init__(
        self,
        clob_client: Any,
        *,
        order_args_cls: Any = None,
        order_type_cls: Any = None,
        buy_const: Any = None,
        sell_const: Any = None,
        paper_mode: bool = False,
    ) -> None:
        self.clob = clob_client
        self._OrderArgs = order_args_cls
        self._OrderType = order_type_cls
        self._BUY = buy_const
        self._SELL = sell_const
        self.paper_mode = paper_mode
        self._paper_counter = 0
        # internal order tag → CLOB order ID
        self._order_map: dict[str, str] = {}

    def execute_commands(self, commands: tuple) -> list[A6OrderResult]:
        """Execute a batch of A6OrderCommand objects against the CLOB.

        Returns one A6OrderResult per command.
        """
        results: list[A6OrderResult] = []
        for cmd in commands:
            try:
                if cmd.action == "PLACE":
                    result = self._place(cmd)
                elif cmd.action == "CANCEL":
                    result = self._cancel(cmd)
                elif cmd.action == "REPLACE":
                    # Cancel old, place new
                    cancel_result = self._cancel(cmd)
                    if not cancel_result.success:
                        logger.warning(
                            "A6 REPLACE cancel failed for %s:%s — placing anyway",
                            cmd.basket_id,
                            cmd.leg_id,
                        )
                    result = self._place(cmd)
                elif cmd.action == "ROLLBACK":
                    result = self._place_sell(cmd)
                else:
                    result = A6OrderResult(
                        command_action=cmd.action,
                        basket_id=cmd.basket_id,
                        leg_id=cmd.leg_id,
                        market_id=cmd.market_id,
                        token_id=cmd.token_id,
                        order_id="",
                        success=False,
                        error=f"unknown action: {cmd.action}",
                    )
                results.append(result)
            except Exception as e:
                logger.error(
                    "A6 command %s failed for %s:%s — %s",
                    cmd.action,
                    cmd.basket_id,
                    cmd.leg_id,
                    e,
                )
                results.append(
                    A6OrderResult(
                        command_action=cmd.action,
                        basket_id=cmd.basket_id,
                        leg_id=cmd.leg_id,
                        market_id=cmd.market_id,
                        token_id=cmd.token_id,
                        order_id="",
                        success=False,
                        error=str(e),
                    )
                )
        return results

    def poll_fill_status(self, order_id: str) -> A6FillStatus | None:
        """Poll the CLOB for current fill status of an order."""
        if self.paper_mode or not order_id or not self.clob:
            return None
        try:
            resp = self.clob.get_order(order_id)
            if not isinstance(resp, dict):
                return None
            original = float(resp.get("original_size", resp.get("size", 0)))
            matched = float(resp.get("size_matched", 0))
            remaining = max(0.0, original - matched)
            status = str(resp.get("status", "unknown")).lower()
            avg_price = float(resp.get("associate_trades_avg_price", resp.get("price", 0)))
            return A6FillStatus(
                order_id=order_id,
                original_size=original,
                size_matched=matched,
                remaining=remaining,
                status=status,
                avg_price=avg_price,
            )
        except Exception as e:
            logger.debug("Failed to poll order %s: %s", order_id[:16], e)
            return None

    def get_clob_order_id(self, internal_id: str) -> str | None:
        """Look up the CLOB order ID for an internal order tag."""
        return self._order_map.get(internal_id)

    def _place(self, cmd) -> A6OrderResult:
        """Place a BUY maker order."""
        if self.paper_mode:
            return self._paper_place(cmd)

        side = self._BUY
        order_args = self._OrderArgs(
            token_id=cmd.token_id,
            price=round(cmd.limit_price, 2),
            size=round(cmd.quantity, 2),
            side=side,
        )
        signed = self.clob.create_order(order_args)
        resp = self.clob.post_order(
            signed,
            self._OrderType.GTC,
            post_only=cmd.post_only,
            neg_risk=bool(getattr(cmd, "neg_risk", False)),
        )

        order_id = ""
        success = False
        error = None
        if isinstance(resp, dict):
            order_id = resp.get("orderID", resp.get("id", ""))
            success = not resp.get("error")
            if not success:
                error = resp.get("error", str(resp))
        else:
            success = bool(resp)
            if not success:
                error = str(resp)

        # Map internal order tag to CLOB order ID
        internal_tag = f"{cmd.basket_id}:{cmd.leg_id}:r{getattr(cmd, '_replace_count', 0)}"
        if order_id:
            self._order_map[internal_tag] = order_id
            # Also map leg_id directly for easy lookup
            self._order_map[cmd.leg_id] = order_id

        return A6OrderResult(
            command_action=cmd.action,
            basket_id=cmd.basket_id,
            leg_id=cmd.leg_id,
            market_id=cmd.market_id,
            token_id=cmd.token_id,
            order_id=order_id,
            success=success,
            error=error,
            raw_response=resp if isinstance(resp, dict) else None,
        )

    def _place_sell(self, cmd) -> A6OrderResult:
        """Place a SELL order (for rollback)."""
        if self.paper_mode:
            return self._paper_place(cmd)

        side = self._SELL
        if side is None:
            # Fallback: SELL constant not available
            logger.error("SELL constant not available — cannot execute rollback")
            return A6OrderResult(
                command_action=cmd.action,
                basket_id=cmd.basket_id,
                leg_id=cmd.leg_id,
                market_id=cmd.market_id,
                token_id=cmd.token_id,
                order_id="",
                success=False,
                error="SELL constant unavailable",
            )

        order_args = self._OrderArgs(
            token_id=cmd.token_id,
            price=round(cmd.limit_price, 2),
            size=round(cmd.quantity, 2),
            side=side,
        )
        signed = self.clob.create_order(order_args)
        resp = self.clob.post_order(
            signed,
            self._OrderType.GTC,
            post_only=cmd.post_only,
            neg_risk=bool(getattr(cmd, "neg_risk", False)),
        )

        order_id = ""
        success = False
        error = None
        if isinstance(resp, dict):
            order_id = resp.get("orderID", resp.get("id", ""))
            success = not resp.get("error")
            if not success:
                error = resp.get("error", str(resp))
        else:
            success = bool(resp)

        return A6OrderResult(
            command_action=cmd.action,
            basket_id=cmd.basket_id,
            leg_id=cmd.leg_id,
            market_id=cmd.market_id,
            token_id=cmd.token_id,
            order_id=order_id,
            success=success,
            error=error,
            raw_response=resp if isinstance(resp, dict) else None,
        )

    def _cancel(self, cmd) -> A6OrderResult:
        """Cancel a resting order by ID."""
        cancel_id = cmd.replaces_order_id or ""
        # Resolve internal tag → CLOB order ID
        clob_id = self._order_map.get(cancel_id) or self._order_map.get(cmd.leg_id) or cancel_id

        if self.paper_mode or not clob_id:
            return A6OrderResult(
                command_action="CANCEL",
                basket_id=cmd.basket_id,
                leg_id=cmd.leg_id,
                market_id=cmd.market_id,
                token_id=cmd.token_id,
                order_id=clob_id,
                success=True,
            )

        try:
            resp = self.clob.cancel(clob_id)
            success = True
            # Remove from map
            keys_to_remove = [k for k, v in self._order_map.items() if v == clob_id]
            for k in keys_to_remove:
                del self._order_map[k]
            return A6OrderResult(
                command_action="CANCEL",
                basket_id=cmd.basket_id,
                leg_id=cmd.leg_id,
                market_id=cmd.market_id,
                token_id=cmd.token_id,
                order_id=clob_id,
                success=True,
            )
        except Exception as e:
            return A6OrderResult(
                command_action="CANCEL",
                basket_id=cmd.basket_id,
                leg_id=cmd.leg_id,
                market_id=cmd.market_id,
                token_id=cmd.token_id,
                order_id=clob_id,
                success=False,
                error=str(e),
            )

    def _paper_place(self, cmd) -> A6OrderResult:
        """Simulate order placement in paper mode."""
        self._paper_counter += 1
        order_id = f"paper-a6-{self._paper_counter}"
        self._order_map[cmd.leg_id] = order_id
        return A6OrderResult(
            command_action=cmd.action,
            basket_id=cmd.basket_id,
            leg_id=cmd.leg_id,
            market_id=cmd.market_id,
            token_id=cmd.token_id,
            order_id=order_id,
            success=True,
        )
