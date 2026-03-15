# Testing Guide for Polymarket Bot

## Quick Start

### Run All Tests
```bash
cd /path/to/elastifund/polymarket-bot
python -m pytest
```

The default pytest config targets `tests/` only and skips historical directories such as `snapshots/`.

### Run with Coverage
```bash
python -m pytest --cov=src --cov-report=term-missing
```

### Run Specific Test Suite
```bash
python -m pytest tests/test_risk.py -v           # Risk management tests
python -m pytest tests/test_paper_broker.py -v   # Broker tests
python -m pytest tests/test_repository.py -v     # Database tests
python -m pytest tests/test_engine.py -v         # Engine tests
python -m pytest tests/test_live_blocked.py -v   # Safety tests
```

## Test Structure

### conftest.py
Shared fixtures and configuration:
- `event_loop` - Async event loop management
- `db_session` - In-memory database for testing

### test_risk.py (9 tests)
Risk management verification:
- Volatility detection
- Position limits
- Rate limiting  
- Kill switch mechanism

### test_paper_broker.py (9 tests)
Broker simulation:
- Order execution
- Cash management
- Position tracking
- Slippage/fees

### test_repository.py (9 tests)
Database operations:
- CRUD operations
- Order lifecycle
- Position management
- Analytics

### test_engine.py (3 tests)
Engine and data flow:
- Mock data feed
- Strategy signals
- Position aggregation

### test_live_blocked.py (2 tests)
Safety verification:
- Live trading disabled by default
- Configuration management

## Test Categories

### Async Tests (30+)
All database and broker operations are async. Tests use `@pytest.mark.asyncio` and proper async/await.

### Unit Tests
Individual component testing:
- Risk manager
- Paper broker
- Repository
- Strategy

### Integration Tests
Component interaction:
- Engine + Data Feed + Strategy
- Broker + Risk Manager
- Database + Repository

## Writing New Tests

### Template
```python
import pytest
from src.module import Component

class TestComponent:
    @pytest.mark.asyncio
    async def test_feature(self, db_session):
        # Arrange
        settings = make_settings(key=value)
        component = Component(settings)
        
        # Act
        result = await component.method(db_session)
        await db_session.commit()
        
        # Assert
        assert result == expected
```

### Database Tests
```python
@pytest.mark.asyncio
async def test_db_operation(self, db_session):
    # Create
    obj = await Repository.create(db_session, ...)
    await db_session.commit()
    
    # Verify
    assert obj.id is not None
```

### Async Tests
```python
@pytest.mark.asyncio
async def test_async_operation(self):
    result = await async_function()
    assert result is not None
```

## Common Assertions

```python
# Equality
assert value == expected
assert value != unexpected

# Containment
assert "substring" in full_string
assert item in collection

# Type checking
assert isinstance(obj, Class)

# Boolean
assert condition is True
assert condition is False

# Length
assert len(collection) == expected_count

# Comparisons
assert number < upper_bound
assert number > lower_bound
```

## Debugging Tests

### Run with Output
```bash
python -m pytest -v -s
```

### Run Single Test
```bash
python -m pytest tests/test_file.py::TestClass::test_method -v
```

### Run with Python Debugger
```bash
python -m pytest --pdb
```

### Show Local Variables on Failure
```bash
python -m pytest -l
```

## Environment Variables for Testing

Tests use mock environment variables set in conftest.py:
- `POLYMARKET_PRIVATE_KEY` = "test_key"
- `POLYMARKET_FUNDER_ADDRESS` = "test_funder"  
- `DATABASE_URL` = "sqlite+aiosqlite:///test.db"
- `LIVE_TRADING` = "false"
- `DASHBOARD_TOKEN` = "test_token"

These prevent accidental live trading during tests.

## Performance Considerations

### In-Memory Database
Tests use SQLite in-memory database (`:memory:`) for speed:
- No disk I/O
- Automatic cleanup
- Isolated per test

### Async Tests
All database operations are non-blocking:
- Tests run faster with proper async
- `pytest-asyncio` handles event loop

### Test Isolation
Each test:
- Gets fresh database
- Independent of other tests
- No test dependencies

## Coverage Report

Generate HTML coverage report:
```bash
python -m pytest --cov=src --cov-report=html
# Open htmlcov/index.html in browser
```

Coverage targets by module:
- `src/risk/` - 90%+ coverage
- `src/broker/` - 85%+ coverage
- `src/store/` - 85%+ coverage
- `src/engine/` - 80%+ coverage
- `src/strategy/` - 75%+ coverage

## CI/CD Integration

For GitHub Actions or similar:
```yaml
- name: Run Tests
  run: python -m pytest --cov=src --cov-report=xml

- name: Upload Coverage
  uses: codecov/codecov-action@v3
```

## Troubleshooting

### Import Errors
Ensure you're in the project root:
```bash
cd /path/to/elastifund/polymarket-bot
```

### Async Errors
- Check `asyncio_mode = "auto"` in pyproject.toml
- Mark async tests with `@pytest.mark.asyncio`
- Use `async def test_name` for async tests

### Database Errors
- Ensure `db_session` fixture is used
- Don't forget `await db_session.commit()`
- Check SQLAlchemy relationships

### Settings Errors
- Use `make_settings()` factory function
- Set all required fields
- Override with `**overrides` parameter

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)
- [SQLAlchemy AsyncIO](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Testing Best Practices](https://docs.pytest.org/en/stable/goodpractices.html)
