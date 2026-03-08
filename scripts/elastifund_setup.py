"""CLI wizard for the Elastifund fork-and-run onboarding flow."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.python.envfile import load_env_file, write_env_file
from shared.python.health import format_checks, run_preflight_checks
from shared.python.onboarding import OnboardingAnswers, build_env_updates, build_runtime_manifest
from shared.python.runtime import ElastifundRuntimeSettings

DEFAULT_NONPROFIT = "veteran-suicide-prevention"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare .env and runtime metadata for Elastifund onboarding.")
    parser.add_argument("--non-interactive", action="store_true", help="Use defaults plus CLI flags.")
    parser.add_argument("--check", action="store_true", help="Run preflight checks against the target env file.")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument("--template-path", default=".env.example")
    parser.add_argument("--runtime-manifest", default="state/elastifund/runtime-manifest.json")
    parser.add_argument("--agent-name", default="")
    parser.add_argument("--run-mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--disable-trading", action="store_true")
    parser.add_argument("--disable-digital-products", action="store_true")
    parser.add_argument("--hub-url", default="")
    parser.add_argument("--hub-external-url", default="")
    parser.add_argument("--hub-bootstrap-token", default="")
    parser.add_argument("--hub-registry-path", default="")
    parser.add_argument("--llm-provider", choices=["anthropic", "openai", "dual"], default="anthropic")
    parser.add_argument("--initial-capital-usd", type=int, default=250)
    parser.add_argument("--trading-capital-pct", type=int, default=70)
    parser.add_argument("--digital-capital-pct", type=int, default=30)
    parser.add_argument("--anthropic-api-key", default="")
    parser.add_argument("--openai-api-key", default="")
    parser.add_argument("--polymarket-api-key", default="")
    parser.add_argument("--polymarket-api-secret", default="")
    parser.add_argument("--polymarket-api-passphrase", default="")
    parser.add_argument("--polymarket-funder", default="")
    parser.add_argument("--polymarket-pk", default="")
    parser.add_argument("--kalshi-api-key-id", default="")
    parser.add_argument("--kalshi-rsa-key-path", default="kalshi/kalshi_rsa_private.pem")
    parser.add_argument("--etsy-api-key", default="")
    parser.add_argument("--etsy-shop-id", default="")
    parser.add_argument("--nonprofit", default=DEFAULT_NONPROFIT)
    args = parser.parse_args(argv)

    env_path = Path(args.env_path)
    template_path = Path(args.template_path)
    runtime_manifest_path = Path(args.runtime_manifest)
    existing_env = load_env_file(env_path if env_path.exists() else template_path)

    if args.check:
        return run_checks(env_path if env_path.exists() else template_path)

    answers = build_answers(args, existing_env) if args.non_interactive else prompt_answers(args, existing_env)
    updates = build_env_updates(existing_env, answers)
    write_env_file(env_path, template_path, updates)
    current_env = load_env_file(env_path)
    runtime_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_manifest_path.write_text(json.dumps(build_runtime_manifest(current_env), indent=2, sort_keys=True))

    print(f"Wrote {env_path}")
    print(f"Wrote {runtime_manifest_path}")
    print("")
    print(format_checks(run_preflight_checks(ElastifundRuntimeSettings.from_env(current_env), current_env)))
    print("")
    print("Next steps:")
    print("  docker compose up --build")
    print("  curl http://localhost:8080/healthz")
    print(
        "  curl "
        f"{current_env.get('ELASTIFUND_HUB_EXTERNAL_URL', current_env.get('ELASTIFUND_HUB_URL', 'http://localhost:8080')).rstrip('/')}/api/v1/agents"
    )
    return 0


def run_checks(path: Path) -> int:
    env = load_env_file(path)
    checks = run_preflight_checks(ElastifundRuntimeSettings.from_env(env), env)
    print(format_checks(checks))
    return 1 if any(check.status == "fail" for check in checks) else 0


def build_answers(args: argparse.Namespace, existing_env: dict[str, str]) -> OnboardingAnswers:
    agent_name = args.agent_name or existing_env.get("ELASTIFUND_AGENT_NAME") or f"{socket.gethostname()}-agent"
    return OnboardingAnswers(
        agent_name=agent_name,
        run_mode=args.run_mode,
        enable_trading=not args.disable_trading,
        enable_digital_products=not args.disable_digital_products,
        hub_url=args.hub_url or existing_env.get("ELASTIFUND_HUB_URL", ""),
        hub_external_url=args.hub_external_url
        or (args.hub_url if args.hub_url else existing_env.get("ELASTIFUND_HUB_EXTERNAL_URL", "")),
        hub_bootstrap_token=args.hub_bootstrap_token or existing_env.get("ELASTIFUND_HUB_BOOTSTRAP_TOKEN", ""),
        hub_registry_path=args.hub_registry_path or existing_env.get("ELASTIFUND_HUB_REGISTRY_PATH", ""),
        llm_provider=args.llm_provider,
        anthropic_api_key=args.anthropic_api_key,
        openai_api_key=args.openai_api_key,
        polymarket_api_key=args.polymarket_api_key,
        polymarket_api_secret=args.polymarket_api_secret,
        polymarket_api_passphrase=args.polymarket_api_passphrase,
        polymarket_funder=args.polymarket_funder,
        polymarket_pk=args.polymarket_pk,
        kalshi_api_key_id=args.kalshi_api_key_id,
        kalshi_rsa_key_path=args.kalshi_rsa_key_path,
        etsy_api_key=args.etsy_api_key,
        etsy_shop_id=args.etsy_shop_id,
        nonprofit=args.nonprofit,
        initial_capital_usd=args.initial_capital_usd,
        trading_capital_pct=args.trading_capital_pct,
        digital_capital_pct=args.digital_capital_pct,
    )


def prompt_answers(args: argparse.Namespace, existing_env: dict[str, str]) -> OnboardingAnswers:
    defaults = build_answers(args, existing_env)
    agent_name = _prompt("Agent name", defaults.agent_name)
    run_mode = _prompt_choice("Run mode", defaults.run_mode, ["paper", "live"])
    enable_trading = _prompt_bool("Enable trading lane", defaults.enable_trading)
    enable_digital = _prompt_bool("Enable digital-products lane", defaults.enable_digital_products)
    hub_url = _prompt("Hub URL for agents", defaults.hub_url or "http://hub-gateway:8080")
    hub_external_url = _prompt(
        "Hub URL to share with peers",
        defaults.hub_external_url or "http://localhost:8080",
    )

    polymarket_api_key = ""
    polymarket_api_secret = ""
    polymarket_api_passphrase = ""
    polymarket_funder = ""
    polymarket_pk = ""
    if enable_trading and _prompt_bool("Configure Polymarket credentials now", False):
        polymarket_api_key = _prompt("Polymarket API key", "")
        polymarket_api_secret = _prompt("Polymarket API secret", "")
        polymarket_api_passphrase = _prompt("Polymarket API passphrase", "")
        polymarket_funder = _prompt("Polymarket wallet address", "")
        polymarket_pk = _prompt("Polymarket private key", "")

    kalshi_api_key_id = ""
    kalshi_rsa_key_path = defaults.kalshi_rsa_key_path
    if enable_trading and _prompt_bool("Configure Kalshi credentials now", False):
        kalshi_api_key_id = _prompt("Kalshi API key ID", "")
        kalshi_rsa_key_path = _prompt("Kalshi RSA key path", defaults.kalshi_rsa_key_path)

    etsy_api_key = ""
    etsy_shop_id = ""
    if enable_digital and _prompt_bool("Configure Etsy credentials now", False):
        etsy_api_key = _prompt("Etsy API key", "")
        etsy_shop_id = _prompt("Etsy shop ID", "")

    llm_provider = _prompt_choice("LLM provider", defaults.llm_provider, ["anthropic", "openai", "dual"])
    anthropic_api_key = _prompt("Anthropic API key", "") if llm_provider in {"anthropic", "dual"} else ""
    openai_api_key = _prompt("OpenAI API key", "") if llm_provider in {"openai", "dual"} else ""
    nonprofit = _prompt("Nonprofit slug", defaults.nonprofit)
    initial_capital_usd = int(_prompt("Initial capital (USD)", str(defaults.initial_capital_usd)))
    trading_capital_pct = int(_prompt("Trading capital %", str(defaults.trading_capital_pct)))
    digital_capital_pct = int(_prompt("Digital-products capital %", str(defaults.digital_capital_pct)))

    return OnboardingAnswers(
        agent_name=agent_name,
        run_mode=run_mode,
        enable_trading=enable_trading,
        enable_digital_products=enable_digital,
        hub_url=hub_url,
        hub_external_url=hub_external_url,
        hub_bootstrap_token=defaults.hub_bootstrap_token,
        hub_registry_path=defaults.hub_registry_path,
        llm_provider=llm_provider,
        anthropic_api_key=anthropic_api_key,
        openai_api_key=openai_api_key,
        polymarket_api_key=polymarket_api_key,
        polymarket_api_secret=polymarket_api_secret,
        polymarket_api_passphrase=polymarket_api_passphrase,
        polymarket_funder=polymarket_funder,
        polymarket_pk=polymarket_pk,
        kalshi_api_key_id=kalshi_api_key_id,
        kalshi_rsa_key_path=kalshi_rsa_key_path,
        etsy_api_key=etsy_api_key,
        etsy_shop_id=etsy_shop_id,
        nonprofit=nonprofit,
        initial_capital_usd=initial_capital_usd,
        trading_capital_pct=trading_capital_pct,
        digital_capital_pct=digital_capital_pct,
    )


def _prompt(label: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_bool(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}


def _prompt_choice(label: str, default: str, choices: list[str]) -> str:
    suffix = "/".join(choices)
    value = input(f"{label} [{suffix}] ({default}): ").strip().lower()
    if not value:
        return default
    if value not in choices:
        raise SystemExit(f"{label} must be one of: {', '.join(choices)}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
