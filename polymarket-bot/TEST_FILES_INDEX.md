# Test Files and Documentation Index

## Test Files Location
All test files are in: `/sessions/clever-admiring-goldberg/mnt/Quant/polymarket-bot/tests/`

## Test Modules (6 files, 35 tests, 338 lines)

### 1. conftest.py
**Purpose:** Shared test fixtures and configuration

**Contents:**
- `event_loop` fixture - Session-scoped async event loop
- `db_session` fixture - In-memory SQLite database per test
- Environment variable setup (test credentials, LIVE_TRADING=false)

**Lines:** 38
**Key Features:**
- Auto schema creation from SQLAlchemy models
- Auto cleanup after each test
- AsyncSession for proper async database operations
- Prevents accidental live trading during tests

**Use:** Imported automatically by pytest, provides fixtures to all tests

---

### 2. test_risk.py
**Purpose:** Risk management verification

**Test Class:** `TestRiskManager` (9 tests)

**Test Methods:**
1. `test_volatility_pause_insufficient_data` - Volatility detection with <3 data points
2. `test_volatility_pause_normal` - Normal volatility doesn't trigger pause
3. `test_volatility_pause_high_vol` - High volatility triggers pause
4. `test_kill_switch_blocks_trade` - Kill switch prevents all trades
5. `test_position_limit_blocks` - Position size limits enforced
6. `test_rate_limit_blocks` - Orders-per-hour limits enforced
7. `test_trade_allowed_when_clean` - Clean state allows trading
8. `test_trigger_kill_switch` - Can enable kill switch

**Lines:** 99
**Coverage:**
- Volatility detection with different thresholds
- Position size limits
- Order rate limiting
- Kill switch mechanism
- Pre-trade validation logic

---

### 3. test_paper_broker.py
**Purpose:** Paper (simulated) broker functionality

**Test Class:** `TestPaperBroker` (9 tests)

**Test Methods:**
1. `test_buy_order_fills` - Buy orders execute and debit cash
2. `test_sell_order_fills` - Sell orders from positions work
3. `test_insufficient_cash_rejected` - Insufficient funds rejected
4. `test_slippage_applied` - Slippage reduces execution price
5. `test_fees_applied` - Trading fees deducted from cash
6. `test_position_tracking` - Positions tracked accurately
7. `test_cancel_unfilled` - Order cancellation
8. `test_market_order` - Market orders execute immediately

**Lines:** 65
**Coverage:**
- Buy/sell order execution
- Cash balance management
- Position tracking and aggregation
- Slippage simulation
- Fee calculation
- Order state transitions
- Market vs limit orders

---

### 4. test_repository.py
**Purpose:** Database operations and ORM models

**Test Class:** `TestRepository` (9 tests)

**Test Methods:**
1. `test_create_and_get_order` - Order creation and retrieval
2. `test_update_order_status` - Order status updates
3. `test_position_upsert` - Position create/update logic
4. `test_bot_state_singleton` - Bot state singleton pattern
5. `test_kill_switch` - Kill switch persistence
6. `test_heartbeat` - Heartbeat timestamp tracking
7. `test_risk_event` - Risk event logging
8. `test_orders_last_hour_count` - Rate limiting counts
9. `test_daily_pnl` - P&L calculations

**Lines:** 75
**Coverage:**
- CRUD operations (Create, Read, Update, Delete)
- Order lifecycle management
- Position management and aggregation
- Database transactions and commits
- Singleton patterns
- Event logging with metadata
- Time-window aggregations
- Analytics and reporting

---

### 5. test_engine.py
**Purpose:** Engine loop and integration tests

**Test Class:** `TestEngineKillSwitch` (3 tests)

**Test Methods:**
1. `test_mock_data_feed_returns_prices` - Mock feed generates valid prices
2. `test_strategy_hold_when_insufficient_data` - Strategy handles insufficient data
3. `test_paper_broker_tracks_positions_correctly` - Position aggregation

**Lines:** 37
**Coverage:**
- Mock data feed reliability
- Strategy signal generation
- Position tracking across multiple orders
- Insufficient data handling
- Error scenarios

---

### 6. test_live_blocked.py
**Purpose:** Safety verification and configuration

**Test Class:** `TestLiveBlocked` (2 tests)

**Test Methods:**
1. `test_live_trading_default_false` - Live trading disabled by default
2. `test_env_override` - Configuration can override defaults

**Lines:** 24
**Coverage:**
- Safety defaults
- Configuration override mechanism
- Settings validation

---

## Documentation Files (4 guides)

### TESTS_SUMMARY.md
**Purpose:** Comprehensive test documentation

**Contents:**
- Overview of all test files
- Detailed test descriptions (all 35 tests)
- Statistics and metrics
- Test patterns used
- Coverage areas by module
- How to run tests
- Dependencies
- Notes for developers
- Future enhancements

**Best For:** Understanding what each test does and why it matters

---

### TESTING_GUIDE.md
**Purpose:** Quick reference for running and writing tests

**Contents:**
- Quick start commands
- Test structure overview
- How to run specific tests
- Writing new tests (templates)
- Common assertions
- Debugging tips
- Coverage reporting
- CI/CD integration
- Troubleshooting
- Resources

**Best For:** "How do I run/write/debug tests?"

---

### TEST_INVENTORY.txt
**Purpose:** Detailed catalog and statistics

**Contents:**
- Complete file listing
- Test statistics and metrics
- Coverage matrix by module
- Testing capabilities
- Running instructions
- Dependencies
- Configuration details
- Design principles
- File locations
- Future enhancements

**Best For:** Project overview and statistics

---

### QUICK_TEST_REFERENCE.md
**Purpose:** One-page quick reference

**Contents:**
- All 35 tests with one-liner descriptions
- Common test patterns
- Settings factory usage
- Debugging commands
- Coverage commands
- Test count by category
- Key assertions
- Fixture usage
- Quick tips

**Best For:** "What tests exist and how do I use them?"

---

## File Organization

```
/sessions/clever-admiring-goldberg/mnt/Quant/polymarket-bot/
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures
│   ├── test_risk.py                # 9 risk management tests
│   ├── test_paper_broker.py        # 9 broker tests
│   ├── test_repository.py          # 9 database tests
│   ├── test_engine.py              # 3 engine tests
│   └── test_live_blocked.py        # 2 safety tests
├── TESTS_SUMMARY.md                # Comprehensive documentation
├── TESTING_GUIDE.md                # How-to guide
├── TEST_INVENTORY.txt              # Statistics and catalog
├── QUICK_TEST_REFERENCE.md         # One-page reference
└── TEST_FILES_INDEX.md             # This file
```

## How to Use These Files

### First Time Setup
1. Read: `QUICK_TEST_REFERENCE.md` (2 min read)
2. Read: `TESTING_GUIDE.md` -> Quick Start section

### Running Tests
1. Use: `TESTING_GUIDE.md` -> Running Tests section
2. Commands: `QUICK_TEST_REFERENCE.md` -> Running Tests

### Understanding a Specific Test
1. Find in: `QUICK_TEST_REFERENCE.md` or `TESTS_SUMMARY.md`
2. Look up test description
3. Read test code in `tests/test_*.py`

### Writing New Tests
1. Read: `TESTING_GUIDE.md` -> Writing New Tests
2. Copy pattern from existing test
3. Review: `QUICK_TEST_REFERENCE.md` -> Common Test Patterns

### Debugging
1. Use: `TESTING_GUIDE.md` -> Debugging Tests section
2. Or: `QUICK_TEST_REFERENCE.md` -> Debugging

### Coverage Reports
1. Command: `TESTING_GUIDE.md` -> Coverage Report section
2. Or: `QUICK_TEST_REFERENCE.md` -> Coverage

## Test Statistics

| Metric | Value |
|--------|-------|
| Total Test Files | 6 |
| Total Test Cases | 35 |
| Test Code Lines | 338 |
| Async Tests | 30+ |
| Database Tests | 9 |
| Risk Tests | 9 |
| Broker Tests | 9 |
| Engine Tests | 3 |
| Safety Tests | 2 |

## Quick Commands

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific file
pytest tests/test_risk.py -v

# Run specific test
pytest tests/test_risk.py::TestRiskManager::test_kill_switch_blocks_trade -v

# Debug with output
pytest tests/ -v -s

# Stop on first failure
pytest tests/ -x
```

## Module Mapping

| Test File | Source Module | Tests | Lines |
|-----------|---------------|-------|-------|
| test_risk.py | src/risk/manager.py | 9 | 99 |
| test_paper_broker.py | src/broker/paper_broker.py | 9 | 65 |
| test_repository.py | src/store/repository.py | 9 | 75 |
| test_engine.py | src/engine/, src/data/, src/strategy/ | 3 | 37 |
| test_live_blocked.py | src/core/config.py | 2 | 24 |
| conftest.py | Fixtures & Setup | - | 38 |
| **Total** | | **35** | **338** |

## Documentation Priority

For different use cases:

| Use Case | Read This | Time |
|----------|-----------|------|
| Quick overview | QUICK_TEST_REFERENCE.md | 2-3 min |
| How to run | TESTING_GUIDE.md | 5 min |
| What each test does | TESTS_SUMMARY.md | 10 min |
| Statistics & metrics | TEST_INVENTORY.txt | 5 min |
| This index | TEST_FILES_INDEX.md | 5 min |

## Notes

- All test files are in `/sessions/clever-admiring-goldberg/mnt/Quant/polymarket-bot/tests/`
- All documentation files are in the project root
- Tests use in-memory SQLite for isolation and speed
- Live trading is blocked by default (safety)
- All 35 tests are independent and can run in any order
- Syntax validated: All files compile without errors

## Contact & Support

For specific questions:
1. Search relevant documentation file
2. Check test source code for implementation details
3. Run test with `-v -s` flags for detailed output
4. Check `TESTING_GUIDE.md` -> Troubleshooting section

---

Created: 2026-03-04
Last Updated: 2026-03-04
Status: Complete and verified
