# Non-Trading Status

**Status Date:** 2026-03-10

## Executive Read

JJ-N has two paths. They are not the same path.

**Manual close gate: OPEN.** Operator can contact 10 staged prospects today. No server needed, no Stripe config needed, no new box needed. The first dollar is reachable now via phone, email, or manual Stripe payment link.

**Automated checkout gate: BLOCKED.** Requires 3 env vars on the new Lightsail box after migration: `PUBLIC_BASE_URL`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.

The artifact shows `status=setup_only` and `launchable=false`. This is stale. The code (`nontrading/first_dollar.py` lines 268-271) only gates on `manual_close_ready` and `fulfillment_surface_ready` — both are `true`. When regenerated on a live stack, the artifact will show `status=launchable`. `checkout_surface_not_ready` and `billing_webhook_not_ready` are not in `launchable_gate_keys`. They are explicitly ignored for the launchable determination.

Current truth in this worktree:

- `nontrading/main.py` builds and runs `RevenuePipeline`
- package-local tests are green: `make test-nontrading` (61 passed)
- repo-root JJ-N tests are green: `pytest -q tests/nontrading` (49 passed)
- deterministic smoke path exists: `make smoke-nontrading`
- live-provider startup is blocked if sender identity is placeholder/unverified — this only blocks the automation loop, not manual close
- Website Growth Audit wedge is code-complete and ready for manual close

---

## Two Paths

### Path 1 — Manual Close (OPEN NOW)

Does not require the new box, Stripe config, or email automation.

**Prospects:** 10 selected from 14 curated, staged in `reports/nontrading/revenue_audit_launch_batch_seed.json`

**Priority order:**
1. HVAC — fit_score 84.23, $2,500 estimated value
2. Landscaping — fit_score 82.15, $2,500 estimated value
3. Pest Control — fit_score 70.74, $2,000 estimated value

**Manual close steps:**
1. Load prospects from `reports/nontrading/revenue_audit_launch_batch_seed.json`
2. Contact HVAC first with personalized outreach on specific SEO/conversion issues
3. Present Website Growth Audit at $500/$1,500/$2,500 depending on scope
4. Accept payment via Stripe Payment Link (dashboard.stripe.com > Payment links) or bank transfer
5. Record order, trigger fulfillment manually via `nontrading/revenue_audit/fulfillment.py`

**Payment acceptance without a live server:**
- Stripe Payment Link — no server needed, create from Stripe Dashboard
- Bank transfer / ACH
- PayPal if prospect prefers

### Path 2 — Automated Checkout (BLOCKED — post-migration only)

Requires exactly 3 env vars on the new VPS after migration:

| Rank | Key | Env Var | Action |
|------|-----|---------|--------|
| 1 | `PUBLIC_BASE_URL` | `JJ_N_WEBSITE_GROWTH_AUDIT_PUBLIC_BASE_URL` | Set to live HTTPS URL after new box migration |
| 2 | `STRIPE_SECRET_KEY` | `STRIPE_SECRET_KEY` | Stripe Dashboard > Developers > API keys |
| 3 | `STRIPE_WEBHOOK_SECRET` | `STRIPE_WEBHOOK_SECRET` | Stripe Dashboard > Webhooks > Add endpoint |

Success URL and cancel URL auto-derive from `PUBLIC_BASE_URL`. No separate action needed.

**Post-migration sequence:**
1. Set 3 env vars in new VPS `.env`
2. Verify offer page at `https://<PUBLIC_BASE_URL>/nontrading/website-growth-audit`
3. Test checkout with `sk_test_` key, confirm Stripe redirect completes
4. Trigger test webhook from Stripe Dashboard, confirm 200 + order in lookup
5. Regenerate `nontrading_first_dollar_status.json` — expect `status=launchable, launchable=true`
6. Gate open — run 10 staged prospects through automated checkout flow

---

## What Exists

### Revenue Agent Path

- CLI/runtime: `nontrading/main.py`
- pipeline: `nontrading/pipeline.py`
- compliance/approval: `nontrading/compliance.py`, `nontrading/approval.py`
- storage/CRM: `nontrading/store.py`, `nontrading/models.py`
- templates/offer assets: `nontrading/email/templates/`, `nontrading/offers/website_growth_audit.py`
- Stripe checkout client: `nontrading/revenue_audit/stripe.py` (HMAC-SHA256, form-encoded POST to /v1/checkout/sessions)
- Webhook verification: `verify_webhook_signature` with 300s timestamp tolerance
- All 8 routes registered in `hub/app/nontrading_api.py`, mounted in `hub/app/main.py`

Implemented behavior:

- CSV lead import and suppression handling
- approval-gated outreach routing
- dry-run sender and provider adapters
- telemetry/event emission and status snapshots
- deterministic pipeline cycle execution

### Digital Product Research Lane

- path: `nontrading/digital_products/`
- deterministic ranking and persistence
- export path for Elastic-ready knowledge docs

---

## Verified Commands (March 9, 2026)

```bash
make test-nontrading
pytest -q tests/nontrading
make smoke-nontrading
```

---

## Blockers That Do NOT Block Manual Close

These are real blockers for automated checkout. They do not prevent first dollar via manual close:

- `checkout_surface_not_ready` — only blocks Stripe hosted checkout
- `billing_webhook_not_ready` — only blocks automated payment verification
- automated email blocked — sender domain placeholder, only blocks automation loop
- `new_box_prerequisite` — only blocks `PUBLIC_BASE_URL`, not manual close

---

## What Does Not Change

- **Active wedge:** Website Growth Audit is the ONLY active wedge. No new offers before first dollar.
- **Pricing:** $500/$1,500/$2,500 tiers frozen until first order confirms conversion rate.
- **Prospect scope:** Run existing 10 selected prospects before expanding pool.
- **No new code needed:** Code is complete. All remaining work is env-var config and operator outreach.

Parked until first dollar:
- recurring_monitor_expansion — zero enrolled clients
- openclaw_comparison — comparison_only, no allocator impact
- new_offer_research — one wedge only until first dollar evidence exists
- better_monitor_upsell_experiment — requires at least one client to upsell

---

## Instance 3 Delivery Contract (First-Dollar & Confidence)

### First-Dollar Wedge

- Keep `Website Growth Audit` as the default outbound/repeatable non-trading wedge until another wedge proves faster first cash with equivalent governance.
- Use one measurable JTN path for ranking:
  `lead_source -> qualification -> offer -> payout_signal -> recurring_loop`.
- Lead source should be inbound or explicitly approved outbound only; no cold automation without compliance checks and approval routing.

### Measurable JTN Path

- Lead Source: qualified imported lead or approved outbound prospect.
- Qualification: website exists + owner signal + measurable growth pain + willingness-to-buy check.
- Offer: `Website Growth Audit` proposal at `$500-$2,500` with 5-day delivery.
- Payout Signal: invoice/checkout/PO acknowledgment and accepted proposal state.
- Recurring Loop: monitoring cadence, renewal intent capture, and follow-up offer at day 14 and day 30.

### Funnel Confidence Contract

For each JJ-N recommendation cycle:

1. Track per-step outcomes with Beta priors:
   - `lead_quality`, `qualification`, `offer_accept`, `payout`.
2. For each step `s`, maintain `α_s, β_s` from outcomes and compute `p_s = α_s/(α_s+β_s)`.
3. JTN confidence for the candidate is `p_path = Π p_s`.
4. Feed allocator as:
   - `arr_expected = expected_arr_delta * p_path`
   - `velocity_expected = expected_improvement_velocity * p_path`
   - `penalty = 0.15 * failed_step_rate_recent`
   - `score = arr_expected + velocity_expected - penalty`.
   - candidates with `p_path < 0.60` stay at `hold` unless operator override explicitly lifts policy.
5. Add explicit failure-feedback:
   - each failed step increases `β` for that stage,
   - recurring failed stage above threshold lowers candidate priority until mitigations are applied.

### 7-Day Non-Trading Cashflow Forecast Output

Each cycle should emit:

- day, expected leads, qualified leads, offers sent, accepted offers, payouts, expected gross ARR, costs, net ARR, and confidence band (P10/P50/P90).
- recovery plan if a forecasted step drops below control limits.

### Top-3 Bottleneck Fixes (Current)

1. First contact execution — operator outreach to 10 staged prospects is the only required action.
2. Offer conversion consistency — qualification copy and proposal sequence need confidence tracking and step-level learning.
3. Billing/fulfillment instrumentation — payout signal and recurring-loop telemetry remain the largest contributor to ARR opacity.

---

## Positioning

JJ-N manual close is open now. The first dollar does not require the new box, Stripe config, or email automation. Automated checkout waits on post-migration env vars only. No new code changes are needed.
