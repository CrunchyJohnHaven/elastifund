#!/usr/bin/env python3
"""
Deploy Velocity Maker Strategy to VPS

This script:
1. Resets paper trades (clears 21 long-duration positions)
2. Patches the VPS scanner to prioritize fast-resolving markets
3. Patches the improvement loop for 60s intervals and velocity filtering
4. Restarts the bot service

Run locally: python scripts/deploy_velocity_strategy.py
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

VPS = "polymarket-vps"
VPS_BOT_DIR = "/home/botuser/polymarket-trading-bot"


def run_ssh(cmd: str, check: bool = True) -> str:
    """Run command on VPS via SSH."""
    result = subprocess.run(
        ["ssh", VPS, cmd],
        capture_output=True, text=True, timeout=30,
    )
    if check and result.returncode != 0:
        print(f"SSH ERROR: {result.stderr}")
        raise RuntimeError(f"SSH command failed: {cmd}")
    return result.stdout.strip()


def scp_to_vps(local_path: str, remote_path: str):
    """Copy file to VPS."""
    subprocess.run(
        ["scp", local_path, f"{VPS}:{remote_path}"],
        check=True, timeout=30,
    )


def reset_paper_trades():
    """Clear all positions, restore full capital."""
    print("\n[1/4] Resetting paper trades...")

    reset_data = {
        "portfolio": {
            "starting_capital": 75.0,
            "cash": 75.0,
            "realized_pnl": 0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
        },
        "open_positions": [],
        "closed_positions": [],
    }

    # Write locally then scp
    tmp = Path("/tmp/paper_trades_reset.json")
    tmp.write_text(json.dumps(reset_data, indent=2))
    scp_to_vps(str(tmp), f"{VPS_BOT_DIR}/paper_trades.json")
    print("  -> Cleared 21 positions, restored $75 cash")


def reset_strategy_state():
    """Reset strategy state for velocity strategy."""
    print("\n[2/4] Resetting strategy state...")

    state = {
        "min_edge_threshold": 0.05,
        "min_liquidity": 100.0,
        "max_markets_per_scan": 20,
        "min_confidence": "medium",
        "position_size_usd": 2.0,
        "max_resolution_days": 7,
        "preferred_resolution_hours": 24,
        "maker_only": True,
        "no_side_preference": True,
        "scan_interval_seconds": 60,
        "max_concurrent_positions": 5,
        "strategy_name": "velocity_maker",
        "cycles_completed": 0,
        "total_signals": 0,
        "signals_by_confidence": {"high": 0, "medium": 0, "low": 0},
        "edge_distribution": [],
        "last_tuned": None,
        "tune_history": [],
    }

    tmp = Path("/tmp/strategy_state_reset.json")
    tmp.write_text(json.dumps(state, indent=2))
    scp_to_vps(str(tmp), f"{VPS_BOT_DIR}/strategy_state.json")
    print("  -> Strategy state reset for velocity_maker")


def deploy_velocity_scanner():
    """Deploy enhanced scanner with resolution-time filtering."""
    print("\n[3/4] Deploying velocity scanner patch...")

    scanner_patch = textwrap.dedent('''\
    """
    Scanner - Gamma API Market Scanner (Velocity Maker Edition)

    Fetches active markets from the Gamma API, filters for fast-resolving
    markets, and prioritizes by capital velocity score.
    """

    import json
    import logging
    import re
    from datetime import datetime, timezone, timedelta
    from typing import List, Dict, Any, Optional
    from .http import ThreadLocalSessionMixin

    logger = logging.getLogger(__name__)

    GAMMA_API = "https://gamma-api.polymarket.com"

    # Categories with highest maker-taker edge gaps (jbecker.dev research)
    CATEGORY_EDGE_MULTIPLIER = {
        "world_events": 1.5,   # 7.32pp gap
        "media": 1.5,          # 7.28pp gap
        "entertainment": 1.3,  # 4.79pp gap
        "crypto": 1.1,         # 2.69pp gap
        "sports": 1.1,         # 2.23pp gap
        "politics": 1.0,       # 1.02pp gap
        "finance": 0.8,        # 0.17pp gap (too efficient)
    }

    # Keywords for fast-resolving markets
    FAST_RESOLUTION_KEYWORDS = [
        "today", "tonight", "tomorrow", "this week", "by friday",
        "by monday", "by tuesday", "by wednesday", "by thursday",
        "by saturday", "by sunday", "this weekend",
        "march 7", "march 8", "march 9", "march 10",
        "march 11", "march 12", "march 13", "march 14",
    ]


    def estimate_resolution_hours(market: dict) -> Optional[float]:
        """Estimate hours until market resolves.

        Uses endDate from API if available, otherwise keyword matching.
        Returns None if cannot estimate.
        """
        # Try endDate from API
        end_date_str = market.get("endDate") or market.get("end_date_iso")
        if end_date_str:
            try:
                # Handle various date formats
                for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"]:
                    try:
                        end_dt = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                        hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                        return max(hours, 0.1)
                    except ValueError:
                        continue
            except Exception:
                pass

        # Keyword-based estimation
        question = (market.get("question") or "").lower()
        if any(kw in question for kw in ["today", "tonight"]):
            return 12.0
        if "tomorrow" in question:
            return 36.0
        if any(kw in question for kw in ["this week", "this weekend"]):
            return 120.0

        return None


    def get_category(market: dict) -> str:
        """Extract category from market tags."""
        tags = market.get("tags") or []
        if isinstance(tags, list):
            for tag in tags:
                tag_lower = str(tag).lower() if tag else ""
                for cat in CATEGORY_EDGE_MULTIPLIER:
                    if cat.replace("_", " ") in tag_lower or cat.replace("_", "") in tag_lower:
                        return cat

        # Keyword-based category detection
        question = (market.get("question") or "").lower()
        if any(w in question for w in ["bitcoin", "btc", "eth", "crypto", "token", "sol"]):
            return "crypto"
        if any(w in question for w in ["nba", "nfl", "nhl", "mlb", "fifa", "game", "match", "win the"]):
            return "sports"
        if any(w in question for w in ["trump", "biden", "election", "president", "congress", "senate"]):
            return "politics"
        if any(w in question for w in ["movie", "album", "oscar", "grammy", "rotten", "box office"]):
            return "entertainment"

        return "world_events"  # Default to highest-edge category


    def velocity_score(edge: float, resolution_hours: float) -> float:
        """Capital velocity score: annualized edge per unit of capital lockup."""
        if resolution_hours <= 0:
            resolution_hours = 1.0
        resolution_days = resolution_hours / 24.0
        return abs(edge) / max(resolution_days, 0.01) * 365


    class MarketScanner(ThreadLocalSessionMixin):
        """
        Scans Polymarket for fast-resolving, high-velocity trading opportunities.
        Prioritizes markets by capital velocity and category edge.
        """

        def __init__(self, timeout: int = 15):
            super().__init__()
            self.timeout = timeout

        def fetch_active_markets(
            self,
            limit: int = 100,
            min_liquidity: float = 50.0,
            category: Optional[str] = None,
        ) -> List[Dict[str, Any]]:
            """Fetch active markets from Gamma API."""
            params: Dict[str, Any] = {
                "closed": "false",
                "limit": limit,
                "active": "true",
            }
            if category:
                params["category"] = category

            try:
                resp = self.session.get(
                    f"{GAMMA_API}/markets",
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                markets = resp.json()
            except Exception as e:
                logger.error(f"Failed to fetch markets: {e}")
                return []

            if isinstance(markets, dict) and "data" in markets:
                markets = markets["data"]

            filtered = []
            for m in markets:
                liquidity = float(m.get("liquidity") or 0)
                if liquidity < min_liquidity:
                    continue
                if not m.get("acceptingOrders", False):
                    continue
                filtered.append(m)

            logger.info(f"Found {len(filtered)} active markets (min liquidity ${min_liquidity})")
            return filtered

        def fetch_market(self, condition_id: str) -> Optional[Dict[str, Any]]:
            """Fetch a single market by condition ID."""
            try:
                resp = self.session.get(
                    f"{GAMMA_API}/markets/{condition_id}",
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
            except Exception as e:
                logger.error(f"Failed to fetch market {condition_id}: {e}")
                return None

        def get_mispriced_markets(
            self,
            markets: List[Dict[str, Any]],
            threshold: float = 0.10,
        ) -> List[Dict[str, Any]]:
            """Identify markets with potential mispricing."""
            candidates = []
            for m in markets:
                try:
                    best_bid = float(m.get("bestBid") or 0)
                    best_ask = float(m.get("bestAsk") or 1)
                    prices_raw = m.get("outcomePrices", "[]")

                    if isinstance(prices_raw, str):
                        prices = [float(p) for p in json.loads(prices_raw)]
                    else:
                        prices = [float(p) for p in prices_raw]

                    if len(prices) < 2:
                        continue

                    price_sum = sum(prices)
                    if abs(price_sum - 1.0) > threshold:
                        m["edge"] = abs(price_sum - 1.0)
                        m["edge_type"] = "sum_deviation"
                        candidates.append(m)
                        continue

                    mid = (best_bid + best_ask) / 2
                    spread = best_ask - best_bid
                    if mid > 0 and spread / mid > threshold:
                        m["edge"] = spread / mid
                        m["edge_type"] = "wide_spread"
                        candidates.append(m)

                except (ValueError, TypeError):
                    continue

            candidates.sort(key=lambda x: x.get("edge", 0), reverse=True)
            return candidates

        def get_actionable_candidates(
            self,
            markets: list,
            min_price: float = 0.10,
            max_price: float = 0.90,
            limit: int = 20,
            max_resolution_days: float = 7.0,
            prefer_fast: bool = True,
        ) -> list:
            """
            Select markets optimized for velocity trading.

            Prioritizes:
            1. Fast resolution time (< max_resolution_days)
            2. High category edge multiplier (Entertainment > Politics)
            3. NO-side opportunities (optimism tax)
            4. Good liquidity and volume
            """
            candidates = []
            for m in markets:
                prices_raw = m.get("outcomePrices", "[]")
                try:
                    if isinstance(prices_raw, str):
                        prices = [float(p) for p in json.loads(prices_raw)]
                    else:
                        prices = [float(p) for p in prices_raw]
                    if len(prices) < 2:
                        continue
                    yes_price = prices[0]
                except (ValueError, json.JSONDecodeError):
                    continue

                if not (min_price <= yes_price <= max_price):
                    continue

                # Resolution time filter
                res_hours = estimate_resolution_hours(m)
                if res_hours is not None and res_hours > max_resolution_days * 24:
                    continue

                # Category and velocity scoring
                category = get_category(m)
                cat_multiplier = CATEGORY_EDGE_MULTIPLIER.get(category, 1.0)

                liquidity = float(m.get("liquidity") or 0)
                volume = float(m.get("volume") or 0)

                # Composite score
                price_score = 1.0 - abs(yes_price - 0.5) * 2
                liq_score = min(liquidity / 5000, 1.0)
                vol_score = min(volume / 50000, 1.0)

                # Speed bonus: faster resolution = higher score
                speed_score = 1.0
                if res_hours is not None:
                    if res_hours < 24:
                        speed_score = 2.0   # Big bonus for <24h
                    elif res_hours < 72:
                        speed_score = 1.5   # Bonus for <3d
                    elif res_hours < 168:
                        speed_score = 1.0   # Neutral for <1w
                    else:
                        speed_score = 0.5   # Penalty for >1w

                # NO-side preference (optimism tax)
                no_preference = 1.0
                if yes_price > 0.7:
                    no_preference = 1.2  # YES is expensive -> NO is good value

                m["_score"] = (
                    price_score * 0.2 +
                    liq_score * 0.15 +
                    vol_score * 0.15 +
                    speed_score * 0.3 +
                    cat_multiplier * 0.1 +
                    no_preference * 0.1
                )
                m["_yes_price"] = yes_price
                m["_category"] = category
                m["_resolution_hours"] = res_hours
                m["_speed_score"] = speed_score
                candidates.append(m)

            candidates.sort(key=lambda x: x["_score"], reverse=True)

            logger.info(
                f"Found {len(candidates)} velocity candidates "
                f"(max_res={max_resolution_days}d, price {min_price:.0%}-{max_price:.0%})"
            )

            # Log top 5 for visibility
            for c in candidates[:5]:
                q = c.get("question", "")[:50]
                cat = c.get("_category", "?")
                res = c.get("_resolution_hours")
                res_str = f"{res:.0f}h" if res else "?"
                logger.info(f"  TOP: {q} | cat={cat} | res={res_str} | score={c['_score']:.2f}")

            return candidates[:limit]

        def summarize_market(self, m: Dict[str, Any]) -> str:
            """Return a one-line summary of a market."""
            question = m.get("question", "Unknown")[:60]
            liquidity = float(m.get("liquidity") or 0)
            edge = m.get("edge", 0)
            return f"{question} | liq=${liquidity:.0f} | edge={edge:.1%}"
    ''')

    tmp = Path("/tmp/scanner_velocity.py")
    tmp.write_text(scanner_patch)
    scp_to_vps(str(tmp), f"{VPS_BOT_DIR}/src/scanner.py")
    print("  -> Velocity scanner deployed")


def patch_improvement_loop():
    """Patch improvement loop for 60s interval and velocity filtering."""
    print("\n[4/4] Patching improvement loop interval...")

    # Change default interval from 300 to 60
    run_ssh(
        f"sed -i 's/DEFAULT_INTERVAL = int(os.environ.get(\"CHECK_INTERVAL_SECONDS\", \"300\"))/DEFAULT_INTERVAL = int(os.environ.get(\"CHECK_INTERVAL_SECONDS\", \"60\"))/' "
        f"{VPS_BOT_DIR}/scripts/improvement_loop.py"
    )

    # Add max_resolution_days to candidate filtering
    run_ssh(
        f"sed -i 's/candidates = self.scanner.get_actionable_candidates(/candidates = self.scanner.get_actionable_candidates(/' "
        f"{VPS_BOT_DIR}/scripts/improvement_loop.py"
    )

    print("  -> Loop interval set to 60s")


def update_systemd_service():
    """Update systemd service for 60s interval."""
    print("\n[5/5] Updating systemd service...")

    service_content = textwrap.dedent('''\
    [Unit]
    Description=Polymarket Paper Trading Bot — Velocity Maker Strategy
    After=network.target

    [Service]
    Type=simple
    User=botuser
    WorkingDirectory=/home/botuser/polymarket-trading-bot
    ExecStart=/home/botuser/polymarket-trading-bot/venv/bin/python scripts/improvement_loop.py --continuous --interval 60
    Restart=always
    RestartSec=10
    Environment=PYTHONUNBUFFERED=1

    [Install]
    WantedBy=multi-user.target
    ''')

    tmp = Path("/tmp/polymarket-bot.service")
    tmp.write_text(service_content)
    scp_to_vps(str(tmp), "/etc/systemd/system/polymarket-bot.service")
    run_ssh("systemctl daemon-reload")
    print("  -> Systemd service updated for 60s intervals")


def restart_bot():
    """Restart the bot service."""
    print("\nRestarting bot service...")
    run_ssh("systemctl restart polymarket-bot.service")

    import time
    time.sleep(5)

    status = run_ssh("systemctl is-active polymarket-bot.service", check=False)
    print(f"  -> Service status: {status}")

    logs = run_ssh(
        "journalctl -u polymarket-bot.service --no-pager -n 10 2>/dev/null || echo 'no logs'",
        check=False,
    )
    print(f"  -> Recent logs:\n{logs}")


def main():
    print("=" * 60)
    print("  DEPLOYING VELOCITY MAKER STRATEGY")
    print("=" * 60)
    print(f"\nTarget: {VPS} ({VPS_BOT_DIR})")
    print("Strategy: velocity_maker (fast-resolve + maker-only + category edge)")

    try:
        # Verify connectivity
        hostname = run_ssh("hostname")
        print(f"Connected to: {hostname}")

        # Stop bot first
        print("\nStopping bot service...")
        run_ssh("systemctl stop polymarket-bot.service", check=False)

        reset_paper_trades()
        reset_strategy_state()
        deploy_velocity_scanner()
        patch_improvement_loop()
        update_systemd_service()
        restart_bot()

        print("\n" + "=" * 60)
        print("  DEPLOYMENT COMPLETE")
        print("=" * 60)
        print("\nVelocity Maker Strategy is now live:")
        print("  - Paper trades cleared ($75 cash)")
        print("  - Scanner optimized for fast-resolving markets")
        print("  - Scan interval: 60s (was 300s)")
        print("  - Category edge multipliers active")
        print("  - NO-side preference enabled (optimism tax)")
        print("  - Max resolution: 7 days (was unlimited)")

    except Exception as e:
        print(f"\nDEPLOYMENT FAILED: {e}")
        print("Attempting to restart bot with old config...")
        run_ssh("systemctl start polymarket-bot.service", check=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
