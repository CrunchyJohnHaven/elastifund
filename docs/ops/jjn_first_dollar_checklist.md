# JJ-N First Dollar Launch Checklist

**Status:** BLOCKED — waiting on manual steps below
**Date:** 2026-03-14
**Offer:** Website Growth Audit ($500 / $1,500 / $2,500)
**Delivery:** 5 business days from payment

---

## What the system has already built

- [x] 14 curated prospect seeds loaded and scored
- [x] Top 10 prospects synced to CRM with accounts, contacts, opportunities
- [x] Audit evidence collected (missing meta descriptions, unclear CTAs, etc.)
- [x] Personalized outreach email drafts for top 3 prospects (see `nontrading/outreach_drafts/`)
- [x] Full outreach package with all 13 prospects, talking points, objection handling (see `reports/nontrading/outreach_package_v1.md`)
- [x] Stripe checkout client built (`nontrading/revenue_audit/stripe.py`)
- [x] Checkout session creation API ready (`nontrading/revenue_audit/service.py`)
- [x] Webhook verification and payment event processing ready
- [x] Fulfillment engine built (`nontrading/revenue_audit/fulfillment.py`)
- [x] Compliance guard (CAN-SPAM) passing
- [x] Conversion engine staging proposals and follow-ups
- [x] Recurring monitor upsell defined ($299/month)

## What John needs to do manually

### Step 1: Create Stripe Payment Links (5 minutes)

1. Go to https://dashboard.stripe.com
2. Navigate to: **Payment Links** > **+ New**
3. Create three links:

| Link Name | Amount | Description |
|-----------|--------|-------------|
| Website Growth Audit: Starter | $500.00 | 5-day delivery. Top 3 quick wins with implementation instructions. |
| Website Growth Audit: Growth | $1,500.00 | 5-day delivery. Full search, conversion, and competitor analysis. |
| Website Growth Audit: Scale | $2,500.00 | 5-day delivery. Comprehensive audit with 90-day implementation roadmap. |

4. Enable "Collect billing address" on each
5. Copy the generated URLs (format: `https://buy.stripe.com/xxxxx`)

### Step 2: Set up a scheduling link (2 minutes)

- Create a Calendly (or Cal.com) link for 15-minute discovery calls
- Or use "reply to schedule" in email templates

### Step 3: Personalize and send first email (5 minutes)

1. Open `nontrading/outreach_drafts/01_fire_and_ice_hvac.md`
2. Replace `[CALENDLY_LINK]` with your actual scheduling link
3. Find the owner/manager name (check their website About page, LinkedIn, or Google Business Profile)
4. Replace "Hi there" with "Hi [First Name]"
5. Send from johnhavenbradley@gmail.com (or professional alias)

### Step 4: Configure Stripe for API integration (optional, for automation)

Only needed if you want the system to create checkout sessions programmatically:

```bash
# Add to .env on the VPS:
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
JJ_REVENUE_PUBLIC_BASE_URL=https://your-actual-domain.com
```

Run `python -m nontrading.checkout --status` to verify configuration.

### Step 5: After payment is received

1. Log the order: company name, tier, amount, payment date
2. Run the fulfillment engine:
   ```bash
   python -m nontrading.revenue_audit.fulfillment --order-id <ID>
   ```
   Or manually prepare the audit report using the evidence already collected
3. Deliver the report via email (PDF) within 5 business days
4. Follow up day 14: "How is implementation going?"
5. Follow up day 30: Recurring monitor upsell ($299/month)

---

## Current blocker summary

| Gate | Status | Fix |
|------|--------|-----|
| offer_defined | PASS | Website Growth Audit is defined |
| pipeline_available | PASS | Pipeline running, prospects scored |
| checkout_surface_ready | BLOCKED | Create Stripe Payment Links (Step 1) |
| billing_webhook_ready | BLOCKED | Set STRIPE_WEBHOOK_SECRET in .env (Step 4) |
| manual_close_ready | PASS | Outreach drafts and package ready |
| fulfillment_surface_ready | PASS | Fulfillment engine built |
| compliance_clear | PASS | CAN-SPAM compliant |

**Minimum viable launch:** Steps 1-3 only. Payment Links + manual email = first dollar possible today. API integration (Step 4) can come later.

---

## Follow-up cadence

- Day 0: Send initial email
- Day 3: Follow up if no response (template in outreach_package_v1.md)
- Day 7: Final follow up
- Day 90: Re-engage if "not now"

## Expected conversion

- 13 prospects in pipeline
- 3 personalized outreach drafts ready
- At $500-$2,500 per audit, first dollar requires 1 conversion
- Conservative estimate: 5-10% response rate on cold outreach = 1-2 conversations from 13 sends
- If 50% of conversations convert: 0.5-1 sale from batch 1
