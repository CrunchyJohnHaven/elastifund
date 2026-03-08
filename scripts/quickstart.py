#!/usr/bin/env python3
"""One-command local bootstrap for first-time Elastifund users."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a local Elastifund checkout and optionally start the Docker stack.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Write .env and stop before starting Docker.")
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
    return parser.parse_args(argv)


def ensure_env_file(env_path: Path, template_path: Path) -> bool:
    if env_path.exists():
        return False
    if not template_path.exists():
        raise FileNotFoundError(f"Template env file not found: {template_path}")
    shutil.copyfile(template_path, env_path)
    return True


def build_setup_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "scripts/elastifund_setup.py",
        "--non-interactive",
        "--env-path",
        args.env_path,
        "--template-path",
        args.template_path,
        "--runtime-manifest",
        args.runtime_manifest,
        "--run-mode",
        args.run_mode,
    ]
    if args.agent_name:
        command.extend(["--agent-name", args.agent_name])
    if args.disable_trading:
        command.append("--disable-trading")
    if args.disable_digital_products:
        command.append("--disable-digital-products")
    if args.hub_url:
        command.extend(["--hub-url", args.hub_url])
    if args.hub_external_url:
        command.extend(["--hub-external-url", args.hub_external_url])
    if args.hub_bootstrap_token:
        command.extend(["--hub-bootstrap-token", args.hub_bootstrap_token])
    if args.hub_registry_path:
        command.extend(["--hub-registry-path", args.hub_registry_path])
    return command


def docker_available() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    result = subprocess.run(
        [docker, "compose", "version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env_path = ROOT / args.env_path
    template_path = ROOT / args.template_path

    created = ensure_env_file(env_path, template_path)
    if created:
        print(f"Created {args.env_path} from {args.template_path}", flush=True)
    else:
        print(f"Using existing {args.env_path}", flush=True)

    print("Running setup wizard in non-interactive mode...", flush=True)
    run(build_setup_command(args))

    if args.prepare_only:
        print("", flush=True)
        print("Preparation complete.", flush=True)
        print("Next step: docker compose up --build", flush=True)
        return 0

    if not docker_available():
        print("", flush=True)
        print("Docker Compose is not available on this machine.", flush=True)
        print("Install Docker Desktop or Docker Engine, then rerun:", flush=True)
        print("  python3 scripts/quickstart.py --prepare-only", flush=True)
        print("  docker compose up --build", flush=True)
        return 1

    print("", flush=True)
    print("Starting the local stack with Docker Compose...", flush=True)
    run(["docker", "compose", "up", "--build"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
