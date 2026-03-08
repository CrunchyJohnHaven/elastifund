"""Bootstrap agent entrypoint used by the fork-and-run onboarding path."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

from shared.python.envfile import is_placeholder_value, load_env_file
from shared.python.runtime import ElastifundRuntimeSettings

from .base import ElastifundAgent

logger = logging.getLogger("elastifund.agent.bootstrap")


class BootstrapDemoAgent(ElastifundAgent):
    def __init__(self, settings: ElastifundRuntimeSettings, env: dict[str, str], state_path: Path):
        super().__init__(settings)
        self.env = env
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def execute_strategy(self) -> dict[str, Any]:
        trading_ready = _configured(
            self.env,
            "POLYMARKET_API_KEY",
            "POLYMARKET_API_SECRET",
            "POLYMARKET_API_PASSPHRASE",
            "POLYMARKET_FUNDER",
            "POLYMARKET_PK",
        )
        digital_ready = _configured(self.env, "ETSY_API_KEY", "ETSY_SHOP_ID") and (
            _configured(self.env, "ANTHROPIC_API_KEY") or _configured(self.env, "OPENAI_API_KEY")
        )
        metrics = {
            "enabled_lanes": sum(
                1
                for enabled in (
                    self.settings.enable_trading,
                    self.settings.enable_digital_products,
                )
                if enabled
            ),
            "trading_ready": trading_ready,
            "digital_products_ready": digital_ready,
            "run_mode": self.settings.run_mode,
            "initial_capital_usd": self.settings.initial_capital_usd,
        }
        self.state_path.write_text(json.dumps(metrics, indent=2, sort_keys=True))
        return metrics

    def report_performance(self, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent_name": self.settings.agent_name,
            "agent_id": self.settings.agent_id,
            "nonprofit": self.settings.nonprofit,
            "capabilities": self.settings.capabilities(),
            "allocation": self.settings.allocation(),
            "lane_status": {
                "trading": "ready" if metrics["trading_ready"] else "configure-keys",
                "digital_products": "ready" if metrics["digital_products_ready"] else "configure-keys",
            },
        }

    def receive_global_model(self, model: Any) -> None:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Elastifund bootstrap agent.")
    parser.add_argument("--run-once", action="store_true", help="Register and emit a single heartbeat.")
    parser.add_argument("--daemon", action="store_true", help="Keep heartbeating at the configured interval.")
    parser.add_argument("--heartbeat-interval", type=int, default=0, help="Override the env heartbeat interval.")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument("--state-path", default="state/elastifund/bootstrap-agent.json")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if not args.run_once and not args.daemon:
        parser.error("choose --run-once or --daemon")

    env = load_env_file(Path(args.env_path))
    settings = ElastifundRuntimeSettings.from_env(env)
    if args.heartbeat_interval:
        settings = settings.__class__(**{**settings.__dict__, "heartbeat_seconds": args.heartbeat_interval})

    agent = BootstrapDemoAgent(settings, env, Path(args.state_path))
    delay = max(5, settings.heartbeat_seconds)

    if args.run_once:
        result = agent.run_once()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    while True:
        try:
            result = agent.run_once()
            logger.info("heartbeat_accepted agent_id=%s status=%s", settings.agent_id, result["status"])
        except RuntimeError as exc:
            logger.warning("hub_registration_pending detail=%s", exc)
        time.sleep(delay)


def _configured(env: dict[str, str], *keys: str) -> bool:
    return all(not is_placeholder_value(env.get(key, "")) for key in keys)


if __name__ == "__main__":
    raise SystemExit(main())
