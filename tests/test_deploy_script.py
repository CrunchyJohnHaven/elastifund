from __future__ import annotations

from pathlib import Path


def test_deploy_script_syncs_runtime_profile_contract_and_uses_systemd_service() -> None:
    script = (Path(__file__).resolve().parent.parent / "scripts" / "deploy.sh").read_text()

    assert 'source <(grep -E \'^(LIGHTSAIL_KEY|VPS_USER|VPS_IP)=\' "$PROJECT_DIR/.env" || true)' in script
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
    assert '"scripts/run_btc5_service.sh"' in script
    assert '"polymarket-bot/src/core/time_utils.py"' in script
    assert 'chmod +x scripts/clean_env_for_profile.sh' in script
    assert 'chmod +x scripts/run_btc5_service.sh scripts/clean_env_for_profile.sh' in script
    assert "from bot.polymarket_runtime import ClaudeAnalyzer, TelegramNotifier" in script
    assert "from bot.runtime_profile import load_runtime_profile" in script
    assert 'SERVICE_NAME="jj-live.service"' in script
    assert '\\"deploy_mode\\": deploy_mode' in script
    assert '\\"paper_trading\\": paper_trading' in script
    assert '"deploy_mode_matches_paper_setting"' in script
    assert "Skipping service restart (--restart not set)." in script
    assert 'sudo journalctl -u $SERVICE_NAME -n 20 --no-pager' in script
    assert "remote state is authoritative; not syncing" in script
    assert '"$VPS:$BOT_DIR/jj_live.py"' not in script
    assert '--btc5-autoresearch Install/enable the BTC5 dual-autoresearch timers' in script
    assert '"btc5_market_model_candidate.py"' in script
    assert '"btc5_command_node.md"' in script
    assert '"infra/fast_json.py"' in script
    assert '"scripts/run_btc5_market_model_mutation_cycle.py"' in script
    assert '"scripts/run_btc5_command_node_mutation_cycle.py"' in script
    assert '"deploy/btc5-market-model-autoresearch.service"' in script
    assert '"deploy/btc5-command-node-autoresearch.service"' in script
    assert '"deploy/btc5-policy-autoresearch.service"' in script
    assert '"deploy/btc5-dual-autoresearch-morning.service"' in script
    assert '"$PROJECT_DIR/$benchmark_dir" -type f | sort' in script
    assert '"${SSH_CMD[@]}" "$VPS" "mkdir -p \\"$BOT_DIR/$remote_parent\\""' in script
    assert 'sudo systemctl enable $BTC5_MARKET_AUTORESEARCH_TIMER_NAME $BTC5_COMMAND_NODE_AUTORESEARCH_TIMER_NAME $BTC5_POLICY_AUTORESEARCH_TIMER_NAME $BTC5_AUTORESEARCH_TIMER_NAME $BTC5_DUAL_MORNING_TIMER_NAME' in script
