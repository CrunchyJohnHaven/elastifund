"""
bot/tests/conftest.py — shared test fixtures for the BTC5 test suite.

BACKWARD-COMPAT FIXTURE
-----------------------
MakerConfig now has fail-closed defaults (direction_filter_enabled=True,
direction_mode=down_only, hour_filter_enabled=True, up_live_mode=shadow_only).

Most process_window tests pre-date this change and set up scenarios that trade
in both directions or trade UP, so they need the old permissive defaults.

The `btc5_permissive_defaults` fixture below sets permissive env vars for those
tests.  It is NOT autouse — tests that want fail-closed production defaults
(i.e., the P0 safety tests in test_btc5_p0_safety.py) must NOT use it, or must
call monkeypatch.delenv() on each var they test.

It IS injected automatically via the marker `@pytest.mark.usefixtures(...)` but
the simplest approach here is an autouse fixture at the function scope that only
applies to this directory.

How the P0 safety tests remain correct:
  Tests in TestFailClosedDefaults explicitly call monkeypatch.delenv() before
  constructing MakerConfig.  monkeypatch.delenv() removes the env var set by
  the autouse fixture, so the test sees the code default, not the env var.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def btc5_test_permissive_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set permissive BTC5 env vars so that pre-existing tests that create
    MakerConfig without direction/filter kwargs continue to work unchanged.

    Tests that specifically verify fail-closed defaults (TestFailClosedDefaults,
    TestStartupSafetyLog) call monkeypatch.delenv() to remove these and see the
    true code defaults.

    This fixture runs at function scope (the default), so each test gets a clean
    monkeypatched environment.
    """
    # Only set if not already explicitly set in the OS environment (i.e., in CI
    # with production env loaded).  In normal test runs, these vars are absent.
    _permissive = {
        "BTC5_DIRECTION_FILTER_ENABLED": "false",
        "BTC5_DIRECTION_MODE": "both",
        "BTC5_HOUR_FILTER_ENABLED": "false",
        # Do NOT override BTC5_UP_LIVE_MODE here — that default (shadow_only)
        # is non-negotiable and the tests that need live_enabled already pass
        # it explicitly via MakerConfig(up_live_mode="live_enabled").
    }
    for name, value in _permissive.items():
        if name not in os.environ:
            monkeypatch.setenv(name, value)
