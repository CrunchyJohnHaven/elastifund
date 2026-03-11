# Instance 3 Operator Packet — JJ-N Manual-Close Activation

**Generated:** 2026-03-10T22:30:00Z
**Instance:** 3 — Claude Code / Sonnet
**Objective:** Use the pre-upgrade period to extract first-dollar value from JJ-N now, not after more infrastructure work.

---

## Verdict: `manual_close_ready_now`

Manual close gate is **OPEN**. Contact 10 staged prospects today. No server, no Stripe config, no new box required.

Automated checkout is **BLOCKED** on exactly 3 env vars post-migration.

---

## Path 1 — Manual Close (DO THIS NOW)

**Gate status:** OPEN
**Requires new box:** No
**Requires Stripe config:** No

### 10 Staged Prospects
Source: `reports/nontrading/revenue_audit_launch_batch_seed.json`

**Priority order:**
1. **HVAC** — fit_score 84.23, $2,500 estimated value — contact first
2. **Landscaping** — fit_score 82.15, $2,500 estimated value
3. **Pest Control** — fit_score 70.74, $2,000 estimated value

### How to Close Without a Live Server

1. Research prospect's website using the SEO/conversion evidence from cycle reports
2. Send personalized outreach (email or LinkedIn) referencing specific issues identified
3. Present Website Growth Audit at $500/$1,500/$2,500 depending on scope conversation
4. Accept payment via **Stripe Payment Link** (create from dashboard.stripe.com > Payments > Payment links — no server needed), bank transfer, or PayPal
5. Record the order manually, trigger `fulfill_order()` from `nontrading/revenue_audit/fulfillment.py`

**First dollar does not require automated checkout, automated email, or a running VPS.**

---

## Path 2 — Automated Checkout (BLOCKED — post-migration only)

**Gate status:** BLOCKED
**Requires new box:** Yes
**Env vars needed:** 3
**Env vars set:** 0

### The Exact 3 Env Vars Required

| Rank | Env Var | Action |
|------|---------|--------|
| 1 | `JJ_N_WEBSITE_GROWTH_AUDIT_PUBLIC_BASE_URL` | Set to live HTTPS URL after new box migration |
| 2 | `STRIPE_SECRET_KEY` | Stripe Dashboard > Developers > API keys |
| 3 | `STRIPE_WEBHOOK_SECRET` | Stripe Dashboard > Webhooks > Add endpoint: `POST https://<PUBLIC_BASE_URL>/v1/nontrading/webhooks/stripe`, event: `checkout.session.completed` |

`SUCCESS_URL` and `CANCEL_URL` auto-derive from `PUBLIC_BASE_URL`. No separate action needed.

### Post-Migration Sequence
1. Set 3 env vars in new VPS `.env`
2. Verify offer page: `https://<PUBLIC_BASE_URL>/nontrading/website-growth-audit`
3. Test checkout with `sk_test_` key, confirm Stripe redirect completes
4. Trigger test webhook from Stripe Dashboard, confirm 200 response + order in lookup
5. Regenerate `nontrading_first_dollar_status.json` — expect `status=launchable, launchable=true`
6. Gate open — run 10 staged prospects through automated checkout flow

---

## Why the Artifact Says `setup_only` (It's Wrong)

`nontrading/first_dollar.py` lines 268-271:
```python
launchable_gate_keys = (
    "manual_close_ready",
    "fulfillment_surface_ready",
)
```

Both are `true`. The artifact's `blocking_reasons` include `checkout_surface_not_ready` and `billing_webhook_not_ready` — these are NOT in `launchable_gate_keys`. The code ignores them for the `launchable` determination. The artifact was generated before the new box was available and has not been regenerated since. When run fresh on a live stack with the new box, it will emit `status=launchable`.

---

## Blockers That Do NOT Block Manual Close

- `checkout_surface_not_ready` — only blocks Stripe hosted checkout
- `billing_webhook_not_ready` — only blocks automated payment verification
- Automated email blocked — sender domain placeholder, only blocks automation loop
- New box prerequisite — only blocks `PUBLIC_BASE_URL`, not manual close

---

## Frozen Constraints

- **Active wedge:** Website Growth Audit only — no new offers before first dollar
- **Pricing:** $500/$1,500/$2,500 frozen until first order confirms conversion
- **Prospect scope:** Contact existing 10 before adding new prospects
- **No new code:** Code is complete. All remaining work is env-var config and operator outreach.

**Parked until first dollar:**
- recurring_monitor_expansion (zero enrolled clients)
- openclaw_comparison (comparison_only, no allocator impact)
- new_offer_research (one wedge only)
- better_monitor_upsell_experiment (requires at least one client)

---

## Required Outputs

| Field | Value |
|-------|-------|
| `candidate_delta_arr_bps` | 6,900 (p50: $260.77 ARR vs $0 current, against $377 portfolio) |
| `expected_improvement_velocity_delta` | +1.0 gate per operator action; manual close gate ALREADY OPEN |
| `arr_confidence_score` | 0.28 (low_to_medium) |
| `finance_gate_pass` | true |
| `one_next_cycle_action` | Contact HVAC prospect (fit_score=84.23, $2,500 est. value) from launch bridge artifact |

---

## Failsafe Rules

- No new Stripe charge attempts until `STRIPE_SECRET_KEY` is live on new box
- No automated checkout claims until all 3 env vars are live and webhook is registered
- No new wedge until first dollar evidence exists
- No prospect expansion until existing 10 are contacted
- Manual close path requires $0 additional capital
