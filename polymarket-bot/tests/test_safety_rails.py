from src.safety import SafetyRails


def test_daily_loss_limit_blocks_trades(monkeypatch):
    monkeypatch.setenv("MAX_DAILY_DRAWDOWN_USD", "10")
    rails = SafetyRails()
    ok, reason = rails.check_pre_trade(1.0, bankroll=100.0, total_exposure_usd=0.0, daily_pnl=-10.0)
    assert ok is False
    assert "Daily loss limit" in reason


def test_exposure_limit_blocks_new_trade(monkeypatch):
    monkeypatch.setenv("MAX_EXPOSURE_PCT", "0.8")
    rails = SafetyRails()
    ok, reason = rails.check_pre_trade(1.0, bankroll=100.0, total_exposure_usd=79.5, daily_pnl=0.0)
    assert ok is False
    assert "Exposure cap" in reason


def test_max_open_positions_blocks(monkeypatch):
    monkeypatch.setenv("MAX_OPEN_POSITIONS", "2")
    rails = SafetyRails()
    ok, reason = rails.check_pre_trade(
        1.0,
        bankroll=100.0,
        total_exposure_usd=0.0,
        daily_pnl=0.0,
        open_positions_count=2,
    )
    assert ok is False
    assert "Max open positions" in reason


def test_single_cycle_cannot_exceed_rollout_limit(monkeypatch):
    monkeypatch.setenv("ROLLOUT_MAX_TRADES_PER_DAY", "3")
    monkeypatch.setenv("MAX_OPEN_POSITIONS", "100")
    rails = SafetyRails()

    allowed = 0
    for _ in range(30):
        ok, _ = rails.check_pre_trade(
            1.0,
            bankroll=1000.0,
            total_exposure_usd=0.0,
            daily_pnl=0.0,
            open_positions_count=allowed,
        )
        if ok:
            rails.record_trade()
            allowed += 1

    assert allowed == 3
