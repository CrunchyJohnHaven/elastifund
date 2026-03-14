"""Stripe checkout helpers for JJ-N Website Growth Audit.

Provides two modes:
1. Payment Link generation (manual): prints Stripe dashboard instructions
2. Checkout Session creation (API): creates hosted checkout sessions via Stripe API

Usage:
    python -m nontrading.checkout --mode payment-links
    python -m nontrading.checkout --mode session --tier starter --email customer@example.com
    python -m nontrading.checkout --status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from nontrading.revenue_audit.config import RevenueAuditSettings
from nontrading.revenue_audit.stripe import StripeCheckoutClient, StripeClientError

logger = logging.getLogger("nontrading.checkout")

TIER_DESCRIPTIONS = {
    "starter": "Top 3 quick wins with implementation instructions.",
    "growth": "Full search, conversion, and competitor analysis with prioritized action plan.",
    "scale": "Comprehensive audit with search gaps, conversion optimization, competitor intelligence, and 90-day implementation roadmap.",
}


def print_payment_link_instructions(settings: RevenueAuditSettings) -> None:
    """Print step-by-step instructions for creating Stripe Payment Links manually."""
    print("=" * 70)
    print("STRIPE PAYMENT LINK SETUP (Manual — 5 minutes)")
    print("=" * 70)
    print()
    print("1. Go to https://dashboard.stripe.com")
    print("2. Navigate to: Payment Links (left sidebar) > + New")
    print("3. Create these three payment links:")
    print()
    for option in settings.pricing:
        amount_cents = int(option.amount_usd * 100)
        desc = TIER_DESCRIPTIONS.get(option.key, option.description)
        print(f"   {option.label} ({option.key})")
        print(f"   Amount: ${option.amount_usd:,.0f} ({amount_cents} cents)")
        print(f"   Description: Website Growth Audit: {option.label}. 5-day delivery. {desc}")
        print()
    print("4. For each link:")
    print("   - Enable 'Collect billing address'")
    print("   - Copy the generated URL (format: https://buy.stripe.com/xxxxx)")
    print()
    print("5. Save the URLs. Paste the appropriate one in outreach emails")
    print("   when a prospect agrees to proceed.")
    print()
    print("After payment, Stripe sends a notification. Start the audit.")
    print("=" * 70)


def create_checkout_session(
    settings: RevenueAuditSettings,
    *,
    tier: str,
    customer_email: str = "",
    client_reference_id: str = "",
) -> dict[str, Any]:
    """Create a Stripe hosted checkout session for the given tier."""
    price = settings.price_option(tier)
    client = StripeCheckoutClient(
        settings.stripe_secret_key,
        api_base=settings.stripe_api_base,
    )
    result = client.create_checkout_session(
        amount_cents=int(price.amount_usd * 100),
        currency=settings.currency,
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        customer_email=customer_email,
        client_reference_id=client_reference_id,
        line_item_name=f"Website Growth Audit: {price.label}",
        line_item_description=price.description,
        metadata={
            "offer_slug": settings.offer_slug,
            "price_key": price.key,
            "amount_usd": str(price.amount_usd),
        },
    )
    return result


def print_status(settings: RevenueAuditSettings) -> None:
    """Print checkout readiness status."""
    print("JJ-N Checkout Readiness Status")
    print("-" * 40)
    print(f"Stripe secret key configured: {'yes' if settings.stripe_secret_key else 'NO'}")
    print(f"Stripe webhook secret configured: {'yes' if settings.stripe_webhook_secret else 'NO'}")
    print(f"Public base URL: {settings.public_base_url}")
    print(f"Public base URL ready: {settings.public_base_url_ready}")
    print(f"Offer URL: {settings.live_offer_url}")
    print(f"Success URL: {settings.stripe_success_url}")
    print(f"Cancel URL: {settings.stripe_cancel_url}")
    print()
    print("Pricing tiers:")
    for option in settings.pricing:
        print(f"  {option.key}: ${option.amount_usd:,.0f} — {option.label}")
    print()

    blockers: list[str] = []
    if not settings.stripe_secret_key:
        blockers.append("Set STRIPE_SECRET_KEY in .env")
    if not settings.stripe_webhook_secret:
        blockers.append("Set STRIPE_WEBHOOK_SECRET in .env")
    if not settings.public_base_url_ready:
        blockers.append("Set JJ_REVENUE_PUBLIC_BASE_URL to a real domain (not example.invalid)")

    if blockers:
        print("BLOCKERS:")
        for blocker in blockers:
            print(f"  - {blocker}")
    else:
        print("STATUS: Ready to create checkout sessions")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JJ-N Stripe checkout helper")
    parser.add_argument(
        "--mode",
        choices=["payment-links", "session", "status"],
        default="status",
        help="Operation mode",
    )
    parser.add_argument("--tier", choices=["starter", "growth", "scale"], help="Price tier for session mode")
    parser.add_argument("--email", default="", help="Customer email for session mode")
    parser.add_argument("--reference", default="", help="Client reference ID for session mode")

    args = parser.parse_args(argv)
    settings = RevenueAuditSettings.from_env()

    if args.mode == "status":
        print_status(settings)
        return 0

    if args.mode == "payment-links":
        print_payment_link_instructions(settings)
        return 0

    if args.mode == "session":
        if not args.tier:
            print("ERROR: --tier is required for session mode", file=sys.stderr)
            return 1
        try:
            result = create_checkout_session(
                settings,
                tier=args.tier,
                customer_email=args.email,
                client_reference_id=args.reference,
            )
            print(json.dumps(result, indent=2))
            return 0
        except StripeClientError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
