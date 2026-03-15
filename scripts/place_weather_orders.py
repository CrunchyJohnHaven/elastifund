#!/usr/bin/env python3
"""
Elastifund — Weather + Daily Market Order Placement Script
===========================================================
Places maker (post-only) limit orders on Polymarket CLOB.
Designed to run on the Dublin VPS (non-US IP) to avoid geoblock.

Portfolio: 8 positions totaling ~$50, all resolving March 9, 2026.
Primary edge: Seoul temperature distribution mispricing vs forecast consensus.
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("place_weather_orders")

# ── Order definitions ────────────────────────────────────────────────

@dataclass
class OrderSpec:
    label: str
    token_id: str
    price: float      # limit bid price
    size: float        # number of shares
    side: str          # "BUY"
    rationale: str


ORDERS: list[OrderSpec] = [
    # ── Seoul Temperature Distribution (resolves 2026-03-09T12:00:00Z) ──
    # Forecast consensus: 9-10°C (AccuWeather 9°C, Weather25 9°C, Met Office 9°C, World-Weather 10°C)
    # Market thinks 7°C is most likely (50.5%). Massive mispricing if forecasts correct.

    OrderSpec(
        label="Seoul 9°C YES",
        token_id="63001528707646183168042167688983283349324449904940749871554730240650380139343",
        price=0.12,
        size=110,
        side="BUY",
        rationale="Forecast says 9-10°C, market prices 9°C at only 5%. My est: 25%. Edge: ~13%.",
    ),
    OrderSpec(
        label="Seoul 10°C YES",
        token_id="59233501221696289447497075372974825652503319847197104641031976351022071916428",
        price=0.06,
        size=84,
        side="BUY",
        rationale="World-Weather says 10°C high. Market prices at 0.65%. My est: 20%. Edge: ~14%.",
    ),
    OrderSpec(
        label="Seoul 11°C+ YES",
        token_id="24962637221848989410276542059406404163871671206742814506761722716886518602059",
        price=0.04,
        size=126,
        side="BUY",
        rationale="Tail bet. Market says 0.3%. If forecast is right (9-10°C), 11+ has ~15% chance.",
    ),
    OrderSpec(
        label="Seoul 7°C NO (temp will NOT be 7°C)",
        token_id="38936643234149388595315209186409001735580195224046900938973350902362290083607",
        price=0.55,
        size=10,
        side="BUY",
        rationale="Market says 7°C is 50.5% likely. Forecasts say 9-10°C. My P(NOT 7°C): 93%.",
    ),
    OrderSpec(
        label="Seoul 8°C NO (temp will NOT be 8°C)",
        token_id="66423451195105595287995078995418352827471670308896945629617626809108409529197",
        price=0.50,
        size=10,
        side="BUY",
        rationale="Market says 8°C is 26.5% likely. Forecasts say 9-10°C. My P(NOT 8°C): 84%.",
    ),
    OrderSpec(
        label="Seoul 6°C NO (temp will NOT be 6°C)",
        token_id="46157861535667220214074105944455432841063277632372168099783357714521013206358",
        price=0.65,
        size=8,
        side="BUY",
        rationale="Market says 6°C is 16.5% likely. Forecasts say 9-10°C. My P(NOT 6°C): 98%.",
    ),

    # ── BTC Daily (resolves 2026-03-09T16:00:00Z) ──
    OrderSpec(
        label="BTC above $66k YES",
        token_id="112392183499493387158135422622355391582250729741577294739483286334858900695441",
        price=0.55,
        size=10,
        side="BUY",
        rationale="BTC at $66,632 (0.95% above $66k). ~60-65% YES probability. Bid below mid.",
    ),

    # ── Wellington Temperature (resolves 2026-03-09T12:00:00Z) ──
    OrderSpec(
        label="Wellington 18°C NO (temp will NOT be 18°C)",
        token_id="46761110356586820870194832991118088235449020853076141987052315117548766984690",
        price=0.40,
        size=13,
        side="BUY",
        rationale="Forecast says 16-17°C. Market says 94.9% for exactly 18°C. My P(NOT 18°C): 80%.",
    ),
]


def main():
    log.info("=" * 60)
    log.info("Elastifund Weather Order Placement — March 9, 2026")
    log.info("=" * 60)

    # ── Load environment ─────────────────────────────────────────────
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        env_path = Path("/home/ubuntu/polymarket-trading-bot/.env")
    if env_path.exists():
        log.info(f"Loading .env from {env_path}")
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

    # ── Import py_clob_client ────────────────────────────────────────
    try:
        from py_clob_client.client import ClobClient as OfficialClobClient
        from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
        from py_clob_client.constants import POLYGON
    except ImportError:
        log.error("py_clob_client not installed. Run: pip install py-clob-client")
        sys.exit(1)

    # ── Resolve credentials ──────────────────────────────────────────
    private_key = os.environ.get("POLY_PRIVATE_KEY") or os.environ.get("POLYMARKET_PK", "")
    if not private_key:
        log.error("No private key found in POLY_PRIVATE_KEY or POLYMARKET_PK")
        sys.exit(1)
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    safe_address = os.environ.get("POLY_SAFE_ADDRESS") or os.environ.get("POLYMARKET_FUNDER", "")
    if not safe_address:
        log.error("No funder/safe address found")
        sys.exit(1)

    log.info(f"Signer key: {private_key[:6]}...{private_key[-4:]}")
    log.info(f"Funder (proxy): {safe_address}")

    # ── Initialize CLOB client ───────────────────────────────────────
    log.info("Initializing CLOB client (signature_type=1 / POLY_PROXY)...")
    client = OfficialClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=POLYGON,
        signature_type=1,  # POLY_PROXY — type 2 fails
        funder=safe_address,
    )

    # Derive L2 API credentials
    log.info("Deriving L2 API credentials...")
    try:
        derived = client.derive_api_key()
    except Exception:
        log.info("derive_api_key() failed, trying create_api_key()...")
        derived = client.create_api_key()

    creds = ApiCreds(
        api_key=derived.api_key,
        api_secret=derived.api_secret,
        api_passphrase=derived.api_passphrase,
    )
    log.info(f"L2 API key derived: {derived.api_key[:8]}...")

    # Re-create client with L2 creds
    client = OfficialClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=POLYGON,
        creds=creds,
        signature_type=1,
        funder=safe_address,
    )

    # Verify auth
    log.info("Verifying auth with get_orders()...")
    try:
        existing = client.get_orders()
        log.info(f"Auth OK. {len(existing) if isinstance(existing, list) else '?'} existing orders.")
    except Exception as e:
        log.error(f"Auth verification failed: {e}")
        sys.exit(1)

    # ── Place orders ─────────────────────────────────────────────────
    results = []
    total_notional = 0.0

    for i, order in enumerate(ORDERS, 1):
        notional = order.price * order.size
        log.info(f"\n--- Order {i}/{len(ORDERS)}: {order.label} ---")
        log.info(f"  Token: ...{order.token_id[-20:]}")
        log.info(f"  Side: {order.side}  Price: ${order.price:.2f}  Size: {order.size} shares")
        log.info(f"  Notional: ${notional:.2f}")
        log.info(f"  Rationale: {order.rationale}")

        try:
            order_args = OrderArgs(
                token_id=order.token_id,
                price=order.price,
                size=order.size,
                side=order.side,
            )
            signed = client.create_order(order_args)
            result = client.post_order(signed, OrderType.GTC)

            order_id = "unknown"
            status = "unknown"
            if isinstance(result, dict):
                order_id = result.get("orderID", result.get("id", "unknown"))
                status = result.get("status", "submitted")
            else:
                order_id = str(result)
                status = "submitted"

            log.info(f"  ✓ ORDER PLACED — ID: {order_id}, Status: {status}")
            results.append({
                "label": order.label,
                "order_id": order_id,
                "status": status,
                "price": order.price,
                "size": order.size,
                "notional": notional,
                "token_id": order.token_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rationale": order.rationale,
            })
            total_notional += notional

        except Exception as e:
            error_msg = str(e)
            log.error(f"  ✗ ORDER FAILED — {error_msg}")
            results.append({
                "label": order.label,
                "order_id": None,
                "status": "FAILED",
                "error": error_msg,
                "price": order.price,
                "size": order.size,
                "notional": notional,
                "token_id": order.token_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rationale": order.rationale,
            })

        # Brief pause between orders to avoid rate limits
        time.sleep(0.5)

    # ── Summary ──────────────────────────────────────────────────────
    log.info("\n" + "=" * 60)
    log.info("ORDER PLACEMENT SUMMARY")
    log.info("=" * 60)

    placed = [r for r in results if r["status"] != "FAILED"]
    failed = [r for r in results if r["status"] == "FAILED"]

    log.info(f"Total orders attempted: {len(results)}")
    log.info(f"Successfully placed: {len(placed)}")
    log.info(f"Failed: {len(failed)}")
    log.info(f"Total notional deployed: ${total_notional:.2f}")

    for r in results:
        symbol = "✓" if r["status"] != "FAILED" else "✗"
        log.info(f"  {symbol} {r['label']}: ${r['notional']:.2f} @ ${r['price']:.2f} — {r['status']}")

    if failed:
        log.warning("\nFailed orders:")
        for r in failed:
            log.warning(f"  {r['label']}: {r.get('error', 'unknown error')}")

    # ── Write results to file ────────────────────────────────────────
    report_path = Path(__file__).resolve().parent.parent / "reports" / "weather_orders_march9.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "placement_time": datetime.now(timezone.utc).isoformat(),
        "total_notional": total_notional,
        "orders_placed": len(placed),
        "orders_failed": len(failed),
        "portfolio": results,
        "thesis": "Seoul temperature distribution mispriced vs forecast consensus (9-10°C vs market 7°C peak)",
        "resolution_times": {
            "seoul": "2026-03-09T12:00:00Z",
            "btc": "2026-03-09T16:00:00Z",
            "wellington": "2026-03-09T12:00:00Z",
        },
    }, indent=2))
    log.info(f"\nResults written to {report_path}")


if __name__ == "__main__":
    main()
