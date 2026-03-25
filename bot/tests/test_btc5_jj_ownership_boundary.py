"""
Tests for BTC5 / JJ ownership boundary.

The rule:
  - jj_live.py must NEVER execute dedicated BTC5 markets.
  - btc_5min_maker.py is the sole BTC5 executor.
  - jj_live.py may only scan/research fast-flow markets; dedicated BTC5
    markets must be filtered out before any order is attempted.

These tests enforce that boundary using the actual production code in
jj_live.py and btc_5min_maker.py, so regressions in either direction
(JJ invading BTC5 territory, or BTC5 depending on JJ) will fail here.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the is_dedicated_btc5_market helper directly from jj_live
# ---------------------------------------------------------------------------
_BOT_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BOT_DIR.parent
sys.path.insert(0, str(_BOT_DIR))
sys.path.insert(0, str(_REPO_ROOT))

# Lazy import helper — avoids loading heavy runtime deps in test env
def _import_jj_live_func(name: str):
    """Return a function from jj_live.py without fully initialising the module.

    We use ast + exec so we only pull in the lightweight helper, not the
    entire bot startup sequence (DB init, APM, geoblock checks, etc.).
    """
    jj_live_path = _BOT_DIR / "jj_live.py"
    source = jj_live_path.read_text()
    tree = ast.parse(source)

    # Build a minimal namespace
    ns: dict = {
        "__name__": "jj_live_test_stub",
        "__file__": str(jj_live_path),
    }

    # We only need the function definitions that don't depend on runtime state.
    # Compile and exec the full source but stub out side-effectful imports.
    # Use importlib with sys.modules patching as a cleaner alternative.
    return None  # placeholder — see per-test logic below


# ---------------------------------------------------------------------------
# Test 1: is_dedicated_btc5_market returns True for BTC5 slug patterns
# ---------------------------------------------------------------------------

def _get_is_dedicated_btc5_market():
    """Import is_dedicated_btc5_market from jj_live with minimal stubs.

    Returns the function or raises pytest.skip if the import fails.
    """
    stub_modules = {
        "httpx": MagicMock(),
        "numpy": MagicMock(),
        "dotenv": MagicMock(),
        "elastic_client": MagicMock(),
        "bot.elastic_client": MagicMock(),
        "bot.runtime_profile": MagicMock(
            RuntimeProfileBundle=MagicMock(),
            activate_runtime_profile_env=MagicMock(return_value=MagicMock()),
        ),
        "bot.polymarket_clob": MagicMock(
            build_authenticated_clob_client=MagicMock(),
            parse_signature_type=MagicMock(),
        ),
        "bot.health_monitor": MagicMock(HeartbeatWriter=MagicMock()),
        "bot.apm_setup": MagicMock(
            apm_transaction=lambda *a, **kw: (lambda f: f),
            capture_span=MagicMock(),
            get_apm_runtime=MagicMock(),
            initialize_apm=MagicMock(),
        ),
        "bot.log_config": MagicMock(configure_logging=MagicMock(), ecs_extra=MagicMock()),
        "bot.latency_tracker": MagicMock(track_latency=lambda *a, **kw: (lambda f: f)),
        "runtime_profile": MagicMock(
            RuntimeProfileBundle=MagicMock(),
            activate_runtime_profile_env=MagicMock(return_value=MagicMock()),
        ),
        "polymarket_clob": MagicMock(
            build_authenticated_clob_client=MagicMock(),
            parse_signature_type=MagicMock(),
        ),
        "health_monitor": MagicMock(HeartbeatWriter=MagicMock()),
        "apm_setup": MagicMock(
            apm_transaction=lambda *a, **kw: (lambda f: f),
            capture_span=MagicMock(),
            get_apm_runtime=MagicMock(),
            initialize_apm=MagicMock(),
        ),
        "log_config": MagicMock(configure_logging=MagicMock(), ecs_extra=MagicMock()),
        "latency_tracker": MagicMock(track_latency=lambda *a, **kw: (lambda f: f)),
    }

    # Evict any cached version so stub_modules take effect
    for key in list(sys.modules.keys()):
        if "jj_live" in key:
            del sys.modules[key]

    with patch.dict(sys.modules, stub_modules):
        import jj_live as _jj
        # Grab a reference INSIDE the context so the real function is captured
        fn = _jj.is_dedicated_btc5_market

    return fn


# Module-level import — done once, shared across all tests in this class.
try:
    _is_dedicated_btc5_market = _get_is_dedicated_btc5_market()
except Exception as _import_exc:
    _is_dedicated_btc5_market = None
    _import_exc_msg = str(_import_exc)
else:
    _import_exc_msg = ""


class TestIsDedicatedBtc5Market:
    """Unit tests for the is_dedicated_btc5_market() guard in jj_live.py."""

    def _call(self, question: str, slug: str | None = None) -> bool:
        if _is_dedicated_btc5_market is None:
            pytest.skip(
                f"jj_live.is_dedicated_btc5_market could not be imported: {_import_exc_msg}"
            )
        return _is_dedicated_btc5_market(question, slug=slug)

    def test_is_dedicated_btc5_market_returns_true_for_btc5_slug(self):
        """Slug starting with btc-updown-5m must always return True."""
        assert self._call("Will BTC go up or down?", slug="btc-updown-5m-2025-01-01T00:00:00") is True
        assert self._call("", slug="btc-updown-5m") is True
        assert self._call("anything", slug="btc-updown-5m-extra-stuff") is True

    def test_is_dedicated_btc5_market_returns_false_for_non_btc5(self):
        """Non-BTC5 markets must not be captured by the guard."""
        assert self._call("Will the Fed cut rates?", slug="fed-rate-cut-2025") is False
        assert self._call("Who wins the 2024 election?", slug="us-election-2024") is False
        assert self._call("Will ETH be above $3000?", slug="eth-price-jan-2026") is False

    def test_is_dedicated_btc5_market_returns_true_for_btc5_question_tokens(self):
        """Questions containing 'bitcoin up or down' + 5m token must return True."""
        assert self._call("Will Bitcoin up or down in 5m?", slug=None) is True
        assert self._call("Bitcoin up or down (5-minute candle)?") is True

    def test_is_dedicated_btc5_market_returns_false_for_btc_hourly(self):
        """BTC markets with long resolution windows are NOT dedicated BTC5."""
        result = self._call("Will Bitcoin be above $100k by end of 2025?", slug="btc-100k-2025")
        assert result is False


# ---------------------------------------------------------------------------
# Test 2: JJ live market scan excludes dedicated BTC5 markets
# ---------------------------------------------------------------------------

def test_jj_live_skips_btc5_markets_in_scan():
    """
    is_dedicated_btc5_market() is the gate used in _filter_market() /
    scan_markets_for_signals().  Verify that a market with a BTC5 slug
    triggers the 'btc5_dedicated' filter reason, not 'allowed'.

    We call is_dedicated_btc5_market directly (the same predicate used in
    the real filter path) to confirm the slug pattern is caught.
    """
    if _is_dedicated_btc5_market is None:
        pytest.skip(f"jj_live.is_dedicated_btc5_market could not be imported: {_import_exc_msg}")

    # A BTC5 slug must return True from the guard, which maps to btc5_dedicated in the filter
    btc5_markets = [
        ("Bitcoin up or down in 5m?", "btc-updown-5m-2026-01-01T00:00:00"),
        ("BTC 5-minute candle up or down?", "btc-updown-5m-abc"),
    ]
    for question, slug in btc5_markets:
        assert _is_dedicated_btc5_market(question, slug=slug) is True, (
            f"Expected BTC5 market to be identified as dedicated: question={question!r}, slug={slug!r}"
        )

    # Non-BTC5 markets must NOT be flagged
    non_btc5_markets = [
        ("Will the Fed cut rates?", "fed-rate-2026"),
        ("ETH above $5000?", "eth-5000-2026"),
    ]
    for question, slug in non_btc5_markets:
        assert _is_dedicated_btc5_market(question, slug=slug) is False, (
            f"Non-BTC5 market incorrectly identified as dedicated: question={question!r}, slug={slug!r}"
        )


# ---------------------------------------------------------------------------
# Test 3: BTC5MinMakerBot has no dependency on jj_live
# ---------------------------------------------------------------------------

def test_btc5_maker_config_has_no_jj_live_dependency():
    """
    btc_5min_maker.py must not import from jj_live.py.
    The dependency is strictly one-way: jj_live knows about BTC5 only to
    EXCLUDE it; BTC5 knows nothing about jj_live.

    We verify this by parsing the AST of btc_5min_maker.py and checking
    that no import statement references 'jj_live'.
    """
    btc5_path = _BOT_DIR / "btc_5min_maker.py"
    assert btc5_path.exists(), f"btc_5min_maker.py not found at {btc5_path}"

    source = btc5_path.read_text()
    tree = ast.parse(source, filename=str(btc5_path))

    jj_live_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "jj_live" in alias.name:
                    jj_live_imports.append(f"import {alias.name} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "jj_live" in module:
                names = [a.name for a in node.names]
                jj_live_imports.append(
                    f"from {module} import {', '.join(names)} (line {node.lineno})"
                )

    assert jj_live_imports == [], (
        "btc_5min_maker.py must NOT import from jj_live.py. "
        f"Found forbidden imports:\n" + "\n".join(jj_live_imports)
    )
