from __future__ import annotations

from html import escape
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from nontrading.revenue_audit.config import RevenueAuditSettings
from nontrading.revenue_audit.contracts import (
    AuditBundle,
    CreateCheckoutRequest,
    IssueEvidence,
    ProspectProfile,
)
from nontrading.revenue_audit.service import RevenueAuditCheckoutService
from nontrading.revenue_audit.stripe import StripeClientError, WebhookVerificationError

router = APIRouter(tags=["nontrading"])


class ProspectProfilePayload(BaseModel):
    business_name: str = Field(min_length=1)
    website_url: str = ""
    contact_email: str = ""
    contact_name: str = ""
    country_code: str = "US"
    industry: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> ProspectProfile:
        return ProspectProfile(**self.model_dump())


class IssueEvidencePayload(BaseModel):
    detector_key: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    severity: str = "medium"
    evidence_url: str = ""
    evidence_snippet: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditBundlePayload(BaseModel):
    bundle_id: str = Field(min_length=1)
    offer_slug: str = "website-growth-audit"
    generated_at: str | None = None
    prospect: ProspectProfilePayload | None = None
    issues: list[IssueEvidencePayload] = Field(default_factory=list)
    score: dict[str, float] = Field(default_factory=dict)
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> AuditBundle:
        payload = self.model_dump()
        if self.prospect is not None:
            payload["prospect"] = self.prospect.to_contract()
        payload["issues"] = tuple(IssueEvidence(**item.model_dump()) for item in self.issues)
        return AuditBundle(**payload)


class CheckoutSessionCreatePayload(BaseModel):
    price_key: str = Field(min_length=1)
    customer_email: str = Field(min_length=3)
    offer_slug: str = "website-growth-audit"
    customer_name: str = ""
    business_name: str = ""
    website_url: str = ""
    success_url: str = ""
    cancel_url: str = ""
    source_order_id: str = ""
    prospect_profile: ProspectProfilePayload | None = None
    audit_bundle: AuditBundlePayload | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> CreateCheckoutRequest:
        return CreateCheckoutRequest(
            price_key=self.price_key,
            customer_email=self.customer_email,
            offer_slug=self.offer_slug,
            customer_name=self.customer_name,
            business_name=self.business_name,
            website_url=self.website_url,
            success_url=self.success_url,
            cancel_url=self.cancel_url,
            source_order_id=self.source_order_id,
            prospect_profile=self.prospect_profile.to_contract() if self.prospect_profile else None,
            audit_bundle=self.audit_bundle.to_contract() if self.audit_bundle else None,
            metadata=self.metadata,
        )


def get_checkout_service() -> RevenueAuditCheckoutService:
    return RevenueAuditCheckoutService(RevenueAuditSettings.from_env())


def _render_offer_page(payload: dict[str, Any]) -> str:
    options = payload["pricing"]["options"]
    option_cards = "".join(
        f"""
        <label class="price-card">
          <input type="radio" name="price_key" value="{escape(option['key'])}" {'checked' if index == 0 else ''}>
          <span class="plan">{escape(option['label'])}</span>
          <strong>${int(option['amount_usd'])}</strong>
          <span>{escape(option.get('description') or '')}</span>
        </label>
        """
        for index, option in enumerate(options)
    )
    checklist = payload["launch_checklist"]
    checklist_rows = "".join(
        f"""
        <li class="check-row {'ready' if item['ready'] else 'missing'}">
          <strong>{escape(item['label'])}</strong>
          <span>{'Ready' if item['ready'] else 'Missing'}</span>
          <small>{escape(item['env'])}: {escape(item['detail'])}</small>
        </li>
        """
        for item in checklist["requirements"]
    )
    blockers = "".join(
        f"<li>{escape(blocker)}</li>"
        for blocker in payload["checkout"]["launch_blockers"]
    ) or "<li>No blocking requirements detected.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(payload['offer']['name'])} | Elastifund</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --paper: rgba(255, 251, 245, 0.9);
      --ink: #1f2023;
      --muted: #5a5f67;
      --accent: #a33a1b;
      --accent-strong: #6f2310;
      --line: rgba(31, 32, 35, 0.12);
      --ok: #1f7a45;
      --warn: #9b3d18;
      --shadow: 0 22px 60px rgba(30, 26, 22, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(163, 58, 27, 0.18), transparent 32rem),
        linear-gradient(180deg, #fff9f0 0%, var(--bg) 100%);
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 64px;
      display: grid;
      gap: 24px;
    }}
    .hero, .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 28px;
      display: grid;
      gap: 18px;
    }}
    h1, h2 {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      font-weight: 700;
      letter-spacing: -0.03em;
    }}
    h1 {{ font-size: clamp(2.2rem, 4vw, 4.3rem); line-height: 0.95; max-width: 12ch; }}
    h2 {{ font-size: 1.35rem; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.6; }}
    .eyebrow {{
      display: inline-flex;
      width: fit-content;
      padding: 0.4rem 0.75rem;
      border-radius: 999px;
      background: rgba(163, 58, 27, 0.1);
      color: var(--accent-strong);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .hero-grid, .panel-grid {{
      display: grid;
      gap: 24px;
    }}
    .hero-grid {{
      grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
      align-items: start;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric {{
      padding: 14px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid var(--line);
    }}
    .metric strong {{
      display: block;
      font-size: 1.25rem;
      margin-bottom: 0.35rem;
    }}
    .panel {{ padding: 24px; }}
    .price-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
      margin-top: 14px;
      margin-bottom: 18px;
    }}
    .price-card {{
      display: grid;
      gap: 6px;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      cursor: pointer;
    }}
    .price-card input {{ margin: 0; }}
    .plan {{
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      font-size: 0.72rem;
    }}
    form {{
      display: grid;
      gap: 12px;
    }}
    label {{
      display: grid;
      gap: 6px;
      font-size: 0.95rem;
    }}
    input, button {{
      font: inherit;
      border-radius: 14px;
    }}
    input {{
      width: 100%;
      border: 1px solid rgba(31, 32, 35, 0.18);
      padding: 0.85rem 0.95rem;
      background: #fff;
    }}
    button {{
      border: 0;
      padding: 0.95rem 1rem;
      background: linear-gradient(135deg, var(--accent), var(--accent-strong));
      color: white;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{
      background: white;
      color: var(--ink);
      border: 1px solid var(--line);
    }}
    ul {{
      margin: 0;
      padding-left: 1.15rem;
      color: var(--muted);
    }}
    .status {{
      min-height: 1.4rem;
      color: var(--accent-strong);
      font-weight: 600;
    }}
    .order-status {{
      padding: 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.9);
      min-height: 68px;
    }}
    .checklist {{
      list-style: none;
      padding: 0;
      display: grid;
      gap: 10px;
    }}
    .check-row {{
      display: grid;
      gap: 4px;
      padding: 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.9);
    }}
    .check-row.ready strong {{ color: var(--ok); }}
    .check-row.missing strong {{ color: var(--warn); }}
    .subtle {{
      font-size: 0.92rem;
      color: var(--muted);
    }}
    @media (max-width: 860px) {{
      .hero-grid {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <span class="eyebrow">JJ-N first-dollar offer</span>
      <div class="hero-grid">
        <div class="hero-copy">
          <h1>{escape(payload['offer']['name'])}</h1>
          <p>{escape(payload['offer']['description'])}</p>
          <div class="metrics">
            <div class="metric">
              <strong>${payload['offer']['price_range_usd']['low']:,} - ${payload['offer']['price_range_usd']['high']:,}</strong>
              <span>Config-backed pricing tiers this cycle.</span>
            </div>
            <div class="metric">
              <strong>{payload['offer']['delivery_days']} days</strong>
              <span>Audit delivery target after payment clears.</span>
            </div>
            <div class="metric">
              <strong>{escape(payload['offer']['fulfillment_type'])}</strong>
              <span>Human-led delivery with repo-tracked fulfillment.</span>
            </div>
          </div>
        </div>
        <div class="panel">
          <h2>Launch posture</h2>
          <p class="subtle">Live offer URL: <code>{escape(payload['checkout']['live_offer_url'])}</code></p>
          <ul>{blockers}</ul>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-grid" style="grid-template-columns: minmax(0, 1fr) minmax(280px, 0.8fr);">
        <div>
          <h2>Open Stripe Checkout</h2>
          <p>Pick a pricing tier, enter the buyer details, and the form will hand off to hosted Stripe Checkout.</p>
          <form id="checkout-form">
            <div class="price-grid">{option_cards}</div>
            <label>
              Work email
              <input id="customer_email" name="customer_email" type="email" placeholder="owner@example.com" required>
            </label>
            <label>
              Contact name
              <input id="customer_name" name="customer_name" type="text" placeholder="Pat Owner">
            </label>
            <label>
              Business name
              <input id="business_name" name="business_name" type="text" placeholder="Acme Builders" required>
            </label>
            <label>
              Website URL
              <input id="website_url" name="website_url" type="url" placeholder="https://acme.example" required>
            </label>
            <button type="submit">Continue to secure Stripe checkout</button>
            <div id="checkout-status" class="status" aria-live="polite"></div>
          </form>
        </div>
        <div>
          <h2>Lookup order status</h2>
          <p>After checkout, use the Stripe session ID from the success page to confirm the paid state and fulfillment queue.</p>
          <form id="lookup-form">
            <label>
              Stripe Checkout session ID
              <input id="lookup_session_id" name="lookup_session_id" type="text" placeholder="cs_live_...">
            </label>
            <button type="submit" class="secondary">Check order status</button>
          </form>
          <div id="lookup-result" class="order-status subtle">No order lookup performed yet.</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>Live-launch checklist</h2>
      <p>The operator truth for this checkout surface. Anything marked missing will keep launch readiness false.</p>
      <ul class="checklist">{checklist_rows}</ul>
    </section>
  </main>
  <script>
    async function checkout(event) {{
      event.preventDefault();
      const statusNode = document.getElementById("checkout-status");
      statusNode.textContent = "Creating hosted checkout session...";
      const formData = new FormData(event.currentTarget);
      const selected = formData.get("price_key");
      const payload = {{
        price_key: selected,
        customer_email: formData.get("customer_email"),
        customer_name: formData.get("customer_name") || "",
        business_name: formData.get("business_name") || "",
        website_url: formData.get("website_url") || ""
      }};
      const response = await fetch("/v1/nontrading/checkout/session", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload)
      }});
      const data = await response.json();
      if (!response.ok) {{
        statusNode.textContent = data.detail || "Unable to create checkout session.";
        return;
      }}
      statusNode.textContent = "Redirecting to Stripe Checkout...";
      window.location.assign(data.checkout_session.hosted_url);
    }}

    async function lookupOrder(event) {{
      event.preventDefault();
      const sessionId = document.getElementById("lookup_session_id").value.trim();
      const resultNode = document.getElementById("lookup-result");
      if (!sessionId) {{
        resultNode.textContent = "Enter a Stripe Checkout session ID first.";
        return;
      }}
      resultNode.textContent = "Fetching order status...";
      const response = await fetch(`/v1/nontrading/orders/lookup?session_id=${{encodeURIComponent(sessionId)}}`);
      const data = await response.json();
      if (!response.ok) {{
        resultNode.textContent = data.detail || "Order lookup failed.";
        return;
      }}
      const order = data.order || {{}};
      resultNode.textContent = `Order ${{order.order_id}} is ${{order.status}} with fulfillment status ${{order.fulfillment_status}}.`;
    }}

    document.getElementById("checkout-form").addEventListener("submit", checkout);
    document.getElementById("lookup-form").addEventListener("submit", lookupOrder);
  </script>
</body>
</html>"""


def _render_success_page(live_offer_url: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Checkout received | Elastifund</title>
  <style>
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #f6f1e8 0%, #fffaf3 100%);
      color: #1f2023;
    }}
    main {{
      max-width: 720px;
      margin: 0 auto;
      padding: 48px 20px 72px;
      display: grid;
      gap: 18px;
    }}
    .card {{
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid rgba(31, 32, 35, 0.12);
      border-radius: 24px;
      padding: 24px;
      box-shadow: 0 18px 45px rgba(30, 26, 22, 0.12);
    }}
    h1 {{
      margin: 0;
      font-family: "Iowan Old Style", Georgia, serif;
      font-size: clamp(2rem, 4vw, 3.2rem);
    }}
    p {{ margin: 0; line-height: 1.6; color: #585c64; }}
    code {{
      padding: 0.15rem 0.35rem;
      border-radius: 8px;
      background: rgba(31, 32, 35, 0.06);
    }}
    a {{ color: #8a3117; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <h1>Checkout received</h1>
      <p>Stripe has redirected back to the Website Growth Audit success surface. This page will look up the repo-tracked order state from the checkout session ID.</p>
    </div>
    <div class="card">
      <p id="status">Waiting for a <code>session_id</code> in the success URL...</p>
      <p><a href="{escape(live_offer_url)}">Back to the offer page</a></p>
    </div>
  </main>
  <script>
    async function loadStatus() {{
      const params = new URLSearchParams(window.location.search);
      const sessionId = params.get("session_id");
      const statusNode = document.getElementById("status");
      if (!sessionId) {{
        statusNode.textContent = "No session_id was present in the success URL.";
        return;
      }}
      statusNode.textContent = `Checking order status for ${{sessionId}}...`;
      const response = await fetch(`/v1/nontrading/orders/lookup?session_id=${{encodeURIComponent(sessionId)}}`);
      const data = await response.json();
      if (!response.ok) {{
        statusNode.textContent = data.detail || "Unable to load order status yet.";
        return;
      }}
      const order = data.order || {{}};
      statusNode.textContent = `Order ${{order.order_id}} is currently ${{order.status}}. Fulfillment status: ${{order.fulfillment_status}}.`;
    }}
    loadStatus();
  </script>
</body>
</html>"""


def _render_cancel_page(live_offer_url: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Checkout canceled | Elastifund</title>
  <style>
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background: #faf5ee;
      color: #1f2023;
    }}
    main {{
      max-width: 720px;
      margin: 0 auto;
      padding: 48px 20px 72px;
      display: grid;
      gap: 16px;
    }}
    .card {{
      background: white;
      border: 1px solid rgba(31, 32, 35, 0.12);
      border-radius: 24px;
      padding: 24px;
    }}
    a {{ color: #8a3117; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <h1>Checkout canceled</h1>
      <p>No payment was recorded on this path. You can reopen the hosted checkout whenever you are ready.</p>
      <p><a href="{escape(live_offer_url)}">Return to the Website Growth Audit offer</a></p>
    </div>
  </main>
</body>
</html>"""


def _render_recurring_monitor_offer_page(payload: dict[str, Any]) -> str:
    offer = payload["offer"]
    checkout = payload["checkout"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(offer['name'])} | Elastifund</title>
  <style>
    body {{ margin: 0; font-family: "Avenir Next", "Segoe UI", sans-serif; background: #faf5ee; color: #1f2023; }}
    main {{ max-width: 760px; margin: 0 auto; padding: 48px 20px 72px; display: grid; gap: 16px; }}
    .card {{ background: white; border: 1px solid rgba(31, 32, 35, 0.12); border-radius: 24px; padding: 24px; }}
    code {{ background: rgba(31, 32, 35, 0.06); padding: 0.15rem 0.35rem; border-radius: 6px; }}
    ul {{ margin: 0; padding-left: 1.2rem; }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <h1>{escape(offer['name'])}</h1>
      <p>{escape(offer['description'])}</p>
      <p><strong>${offer['price_range_usd']['low']:.2f}/month</strong> billed via hosted Stripe Checkout every {offer['cadence_days']} days.</p>
      <p>This upsell attaches to an existing paid Website Growth Audit order. Start checkout through <code>/v1/nontrading/checkout/session</code> with <code>offer_slug={escape(offer['slug'])}</code> and the source audit <code>order_id</code>.</p>
      <ul>
        <li>Checkout mode: {escape(checkout['mode'])}</li>
        <li>Launch ready: {escape(str(checkout['launch_ready']).lower())}</li>
        <li>Checkout endpoint: <code>/v1/nontrading/checkout/session</code></li>
      </ul>
    </div>
  </main>
</body>
</html>"""


@router.get("/v1/nontrading/offers/website-growth-audit")
def website_growth_audit_offer() -> dict[str, Any]:
    return get_checkout_service().offer_payload()


@router.get("/v1/nontrading/offers/website-growth-audit/recurring-monitor")
def website_growth_audit_recurring_monitor_offer() -> dict[str, Any]:
    return get_checkout_service().recurring_monitor_offer_payload()


@router.get("/v1/nontrading/offers/website-growth-audit/launch-checklist")
def website_growth_audit_launch_checklist() -> dict[str, Any]:
    return get_checkout_service().launch_checklist_payload()


@router.get("/nontrading/website-growth-audit", response_class=HTMLResponse)
def website_growth_audit_offer_page() -> HTMLResponse:
    service = get_checkout_service()
    return HTMLResponse(_render_offer_page(service.offer_payload()))


@router.get("/nontrading/website-growth-audit/monitor", response_class=HTMLResponse)
def website_growth_audit_monitor_offer_page() -> HTMLResponse:
    service = get_checkout_service()
    return HTMLResponse(_render_recurring_monitor_offer_page(service.recurring_monitor_offer_payload()))


@router.get("/nontrading/website-growth-audit/success", response_class=HTMLResponse)
def website_growth_audit_success_page() -> HTMLResponse:
    service = get_checkout_service()
    return HTMLResponse(_render_success_page(service.settings.live_offer_url))


@router.get("/nontrading/website-growth-audit/cancel", response_class=HTMLResponse)
def website_growth_audit_cancel_page() -> HTMLResponse:
    service = get_checkout_service()
    return HTMLResponse(_render_cancel_page(service.settings.live_offer_url))


@router.get("/nontrading/website-growth-audit/monitor/success", response_class=HTMLResponse)
def website_growth_audit_monitor_success_page() -> HTMLResponse:
    service = get_checkout_service()
    return HTMLResponse(_render_success_page(service.settings.recurring_monitor_live_offer_url))


@router.get("/nontrading/website-growth-audit/monitor/cancel", response_class=HTMLResponse)
def website_growth_audit_monitor_cancel_page() -> HTMLResponse:
    service = get_checkout_service()
    return HTMLResponse(_render_cancel_page(service.settings.recurring_monitor_live_offer_url))


@router.post("/v1/nontrading/checkout/session")
def create_checkout_session(payload: CheckoutSessionCreatePayload) -> dict[str, Any]:
    service = get_checkout_service()
    try:
        return service.create_checkout_session(payload.to_contract())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StripeClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/v1/nontrading/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    service = get_checkout_service()
    try:
        return service.handle_stripe_webhook(payload, signature)
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/v1/nontrading/orders/lookup")
def lookup_order(
    order_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    payment_intent: str | None = Query(default=None),
) -> dict[str, Any]:
    if not any((order_id, session_id, payment_intent)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide order_id, session_id, or payment_intent for lookup.",
        )
    service = get_checkout_service()
    try:
        return service.get_order_payload(
            order_id,
            provider_session_id=session_id,
            provider_payment_intent_id=payment_intent,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/v1/nontrading/orders/{order_id}")
def get_order(order_id: str) -> dict[str, Any]:
    service = get_checkout_service()
    try:
        return service.get_order_payload(order_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
