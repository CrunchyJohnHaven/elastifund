# Polymarket Bot - Quick Test Reference

## Test Files at a Glance

### tests/conftest.py - Shared Fixtures
```python
@pytest.fixture(scope="session")
def event_loop()
  # Session-scoped async event loop

@pytest_asyncio.fixture
async def db_session()
  # Fresh in-memory SQLite per test
  # Auto schema creation/cleanup
```

---

### tests/test_risk.py - Risk Management (9 tests)

**TestRiskManager class methods:**

1. `test_volatility_pause_insufficient_data()`
   - Tests volatility check with < 3 data points
   - Expects: No pause triggered

2. `test_volatility_pause_normal()`
   - Stable prices [0.50-0.502]
   - Expects: No pause

3. `test_volatility_pause_high_vol()`
   - Wild swings [0.20-0.80]
   - Expects: Pause triggered

4. `test_kill_switch_blocks_trade(db_session)`
   - Enable kill switch, attempt trade
   - Expects: Trade blocked, reason includes "kill switch"

5. `test_position_limit_blocks(db_session)`
   - Max position: $50, try to add $20 to $40 position
   - Expects: Blocked, reason includes "limit"

6. `test_rate_limit_blocks(db_session)`
   - Max 2 orders/hour, create 2 orders, try 3rd
   - Expects: Blocked, reason includes "rate"

7. `test_trade_allowed_when_clean(db_session)`
   - Fresh state, no restrictions
   - Expects: allowed=True, reason="OK"

8. `test_trigger_kill_switch(db_session)`
   - Explicitly trigger kill switch
   - Expects: Persisted in database

---

### tests/test_paper_broker.py - Broker Simulation (9 tests)

**TestPaperBroker class methods:**

1. `test_buy_order_fills()`
   - Buy 100 @ $0.5
   - Expects: Filled, cash = 950

2. `test_sell_order_fills()`
   - Buy 100, then sell 50
   - Expects: Both filled

3. `test_insufficient_cash_rejected()`
   - Try to buy $50 with $10 cash
   - Expects: Rejected, filled_size=0

4. `test_slippage_applied()`
   - Buy with 1% slippage (100 bps)
   - Expects: Cash < 950 (worse execution)

5. `test_fees_applied()`
   - Buy with 1% trading fee (100 bps)
   - Expects: Cash < 950

6. `test_position_tracking()`
   - Buy 100 shares
   - Expects: 1 position with size=100

7. `test_cancel_unfilled()`
   - Try to cancel rejected order
   - Expects: Returns False

8. `test_market_order()`
   - Place market order
   - Expects: Immediately filled

---

### tests/test_repository.py - Database Operations (9 tests)

**TestRepository class methods:**

1. `test_create_and_get_order(db_session)`
   - Create BUY order
   - Expects: Has ID, correct market_id and side

2. `test_update_order_status(db_session)`
   - Create order, mark FILLED with amount
   - Expects: Status and filled_size persisted

3. `test_position_upsert(db_session)`
   - Create position (100 @ 0.5)
   - Update to (200 @ 0.55)
   - Expects: Size and price both updated

4. `test_bot_state_singleton(db_session)`
   - Call get_or_create twice
   - Expects: Both return same object, id=1

5. `test_kill_switch(db_session)`
   - Toggle kill switch
   - Expects: Defaults False, can set True

6. `test_heartbeat(db_session)`
   - Update heartbeat
   - Expects: last_heartbeat is not None

7. `test_risk_event(db_session)`
   - Create risk event
   - Expects: Persisted with correct type

8. `test_orders_last_hour_count(db_session)`
   - Create 2 orders
   - Expects: Count returns 2

9. `test_daily_pnl(db_session)`
   - Create position with $10.5 realized P&L
   - Expects: get_daily_pnl returns 10.5

---

### tests/test_engine.py - Engine Integration (3 tests)

**TestEngineKillSwitch class methods:**

1. `test_mock_data_feed_returns_prices()`
   - Query mock feed
   - Expects: Price in range [0.01, 0.99]

2. `test_strategy_hold_when_insufficient_data()`
   - Generate signal with minimal data
   - Expects: action="hold", reason contains "insufficient"

3. `test_paper_broker_tracks_positions_correctly()`
   - Buy 100 @ 0.5, buy 50 @ 0.6
   - Expects: 1 aggregated position of 150

---

### tests/test_live_blocked.py - Safety Checks (2 tests)

**TestLiveBlocked class methods:**

1. `test_live_trading_default_false()`
   - Create Settings without live_trading param
   - Expects: live_trading=False

2. `test_env_override()`
   - Create Settings with live_trading=True
   - Expects: live_trading=True

---

## Common Test Patterns

### Database Test Pattern
```python
@pytest.mark.asyncio
async def test_name(self, db_session):
    # Create
    obj = await Repository.create(db_session, args)
    await db_session.commit()
    
    # Verify
    assert obj.id is not None
```

### Risk Manager Test Pattern
```python
settings = make_settings(max_position_usd=100.0)
rm = RiskManager(settings)
rm.record_price_time("token")

allowed, reason = await rm.check_pre_trade(
    db_session, "market", "token", "buy", size, price
)
assert allowed is False
assert "substring" in reason.lower()
```

### Broker Test Pattern
```python
broker = PaperBroker(initial_cash=1000, slippage_bps=0, fee_bps=0)
order = await broker.place_order("mkt", "tok", OrderSide.BUY, 0.5, 100)
assert order.status == OrderStatus.FILLED
assert broker.get_cash() == 950.0
```

---

## Running Tests

### All Tests
```bash
pytest tests/ -v
```

### By File
```bash
pytest tests/test_risk.py -v
pytest tests/test_paper_broker.py -v
pytest tests/test_repository.py -v
pytest tests/test_engine.py -v
pytest tests/test_live_blocked.py -v
```

### By Class
```bash
pytest tests/test_risk.py::TestRiskManager -v
pytest tests/test_paper_broker.py::TestPaperBroker -v
```

### By Test
```bash
pytest tests/test_risk.py::TestRiskManager::test_kill_switch_blocks_trade -v
```

### With Coverage
```bash
pytest tests/ --cov=src --cov-report=html
```

---

## Settings Factory

```python
def make_settings(**overrides) -> Settings:
    defaults = {
        "polymarket_private_key": "test",
        "polymarket_funder_address": "test",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "max_position_usd": 100.0,
        "max_daily_drawdown_usd": 50.0,
        "max_orders_per_hour": 10,
        "engine_loop_seconds": 60,
    }
    defaults.update(overrides)
    return Settings(**defaults)

# Usage
settings = make_settings(max_position_usd=50.0)  # Override one field
```

---

## Environment Setup (Auto in conftest.py)

```python
os.environ["POLYMARKET_PRIVATE_KEY"] = "test_key"
os.environ["POLYMARKET_FUNDER_ADDRESS"] = "test_funder"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test.db"
os.environ["LIVE_TRADING"] = "false"  # SAFETY: Prevents live trading
os.environ["DASHBOARD_TOKEN"] = "test_token"
```

---

## Debugging

### Show print() output
```bash
pytest tests/ -v -s
```

### Stop on first failure
```bash
pytest tests/ -x
```

### Enter debugger on failure
```bash
pytest tests/ --pdb
```

### Show local variables on failure
```bash
pytest tests/ -l
```

### Run single test with verbose SQL
```bash
pytest tests/test_repository.py::TestRepository::test_create_and_get_order -vv -s
```

---

## Coverage

### Generate HTML report
```bash
pytest tests/ --cov=src --cov-report=html
# Open htmlcov/index.html in browser
```

### Terminal report
```bash
pytest tests/ --cov=src --cov-report=term-missing
```

### By module
```bash
pytest tests/test_risk.py --cov=src.risk --cov-report=term-missing
```

---

## Test Count by Category

| Category | Count | File |
|----------|-------|------|
| Risk Management | 9 | test_risk.py |
| Broker Simulation | 9 | test_paper_broker.py |
| Repository/Database | 9 | test_repository.py |
| Engine Integration | 3 | test_engine.py |
| Safety | 2 | test_live_blocked.py |
| **TOTAL** | **35** | **6 files** |

---

## Key Assertions

```python
# Equality
assert value == expected
assert status == OrderStatus.FILLED

# Membership
assert "kill switch" in reason.lower()
assert item in collection

# Boolean
assert allowed is False
assert state.last_heartbeat is not None

# Numeric
assert len(positions) == 1
assert cash < 950.0
assert count == 2
```

---

## Fixture Usage

```python
# Database fixture (async)
async def test_something(self, db_session):
    obj = await Repository.create(db_session, ...)
    await db_session.commit()

# Event loop fixture (auto)
# No need to explicitly use - enables async tests
```

---

## Notes

- All tests are isolated - no dependencies between tests
- Database resets after each test
- Environment variables set before any imports
- Live trading blocked by default (safety)
- Async/await properly handled with pytest-asyncio
- No real API calls (uses mock data and in-memory DB)

---

See TESTING_GUIDE.md and TESTS_SUMMARY.md for more details.
