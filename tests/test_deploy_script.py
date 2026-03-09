from __future__ import annotations

from pathlib import Path


def test_deploy_script_syncs_runtime_profile_contract_and_uses_systemd_service() -> None:
    script = (Path(__file__).resolve().parent.parent / "scripts" / "deploy.sh").read_text()

    assert 'source "$PROJECT_DIR/.env"' in script
    assert 'for local_path in "$PROJECT_DIR"/bot/*.py; do' in script
    assert 'sync_file "config/__init__.py"' in script
    assert 'sync_file "config/runtime_profile.py"' in script
    assert '"$PROJECT_DIR"/config/runtime_profiles/*.json' in script
    assert '--clean-env' in script
    assert '--profile NAME' in script
    assert '--restart' in script
    assert 'sync_file "data/wallet_scores.db"' in script
    assert 'sync_file "data/smart_wallets.json"' in script
    assert 'data/wallet_scores.db' in script
    assert '"scripts/clean_env_for_profile.sh"' in script
    assert '"polymarket-bot/src/core/time_utils.py"' in script
    assert 'chmod +x scripts/clean_env_for_profile.sh' in script
    assert "from bot.polymarket_runtime import ClaudeAnalyzer, TelegramNotifier" in script
    assert "from bot.runtime_profile import load_runtime_profile" in script
    assert 'SERVICE_NAME="jj-live.service"' in script
    assert "Skipping service restart (--restart not set)." in script
    assert 'sudo journalctl -u $SERVICE_NAME -n 20 --no-pager' in script
    assert "remote state is authoritative; not syncing" in script
    assert '"$VPS:$BOT_DIR/jj_live.py"' not in script
