# Execution Upgrade: File Change Log

**Sprint**: Maker/Limit Orders + Shadow-Live Mode + Kill-Switch Hardening
**Date**: 2026-03-05
**Tests**: 20 new tests (all passing), 258 total suite passing

---

## Modified Files

### `src/core/config.py`
- Added `execution_mode` (TAKER|MAKER|HYBRID, default MAKER)
- Added `maker_replace_timeout_seconds` (default 30)
- Added `maker_max_retries` (default 3)
- Added `taker_fee_rate` (default 0.025)
- Added `kill_cooldown_seconds` (default 300)

### `src/store/models.py`
- Added `ShadowOrder` model (table `shadow_orders`) with fields: market_id, token_id, side, price, size, execution_mode, would_have_filled, estimated_fee, signal_edge, created_at
- Extended `BotState` with `kill_latched_at` and `kill_cooldown_until` columns

### `src/store/repository.py`
- `set_kill_switch()` now sets `kill_latched_at` and `kill_cooldown_until` when enabling
- New `clear_kill_switch()` — enforces cooldown before allowing disable, returns (success, message)
- `get_kill_switch()` — returns True if cooldown still active
- New `is_kill_cooldown_active()` — check cooldown timer
- New `create_shadow_order()` — insert ShadowOrder row

### `src/broker/base.py`
- New `KillSwitchActiveError` exception
- New `_assert_kill_switch_clear()` async gate (checks DB kill-switch + cooldown)
- `place_order()` and `place_market_order()` now call both `_assert_trading_allowed()` AND `_assert_kill_switch_clear()`

### `src/broker/polymarket_broker.py`
- Extended `_open_orders` tracking with `retries`, `edge`, `side_enum` fields
- New `set_order_edge(order_id, edge)` — set edge for HYBRID fallback decision
- Rewrote `check_and_cancel_timed_out_orders()` with execution-mode-aware logic:
  - MAKER: cancel/replace at current price up to max_retries, then cancel
  - HYBRID: same as MAKER but falls back to taker after max_retries
  - TAKER: cancel outright
- New `cancel_and_replace_order()` — cancel + re-place at updated price, propagates retry count
- New `_do_taker_fallback()` — HYBRID only, places aggressive order if `edge - fee > 0`

### `src/broker/paper_broker.py`
- After successful paper fill, records `ShadowOrder` via `Repository.create_shadow_order()`
- Calculates estimated fee (0 for MAKER, `p*(1-p)*r` for TAKER)
- Wrapped in try/except so shadow write failures don't break paper trading

### `src/engine/loop.py`
- `_cancel_timed_out_orders()` gathers current prices and passes to broker with `maker_replace_timeout_seconds`
- New `_kill_switch_cancel_all()` — cancels all open orders when kill switch activates
- Kill-switch check in main loop calls `_kill_switch_cancel_all()`
- After order placement, calls `broker.set_order_edge()` for HYBRID fallback tracking

### `src/app/dashboard.py`
- `/kill` endpoint: sets kill_switch + latch + cooldown, cancels all open orders, sends Telegram alert
- `/unkill` endpoint: enforces cooldown via `Repository.clear_kill_switch()`, returns HTTP 423 if cooldown active

## New Files

### `tests/test_kill_switch.py` (8 tests)
- `TestKillSwitchLatch`: kill enables+latches, get_kill_switch returns true, cooldown blocks
- `TestUnkillCooldown`: blocked during cooldown, succeeds after, is_kill_cooldown_active
- `TestKillBlocksOrders`: KillSwitchActiveError raised on paper broker
- `TestKilledStateZeroOrders`: integration smoke — killed state produces 0 orders

### `tests/test_execution_mode.py` (12 tests)
- `TestExecutionModeConfig`: default MAKER, HYBRID mode, taker_fee_rate
- `TestMakerMode`: limit order at target price
- `TestCancelReplace`: retry tracking, set_order_edge
- `TestHybridFallback`: skip when no edge, attempt when edge positive
- `TestShadowOrders`: shadow recorded, taker fee, model fields
- `TestPaperBrokerShadowIntegration`: paper broker writes shadow order to DB

## Design Decisions

1. **Kill-switch fail-open at broker level**: `_assert_kill_switch_clear()` uses `logger.warning("kill_switch_check_failed_open")` on DB errors. Rationale: engine loop and risk manager also check independently; a DB connection issue shouldn't block all paper trading.
2. **Shadow writes are best-effort**: Wrapped in try/except in paper_broker to avoid breaking paper trading if DB is unavailable.
3. **Python 3.9 compatibility**: Used `Optional[X]` instead of `X | None` union syntax throughout.
4. **Taker fee formula**: `fee = price * (1 - price) * taker_fee_rate` per Polymarket CLOB spec.
