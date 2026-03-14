# First Non-Trading Dollar Playbook

**Status:** READY TO EXECUTE
**Created:** 2026-03-14
**Author:** JJ (Non-Trading Command Node)

---

## The Problem

97 Python modules. 61 tests. 24 SQLite tables. 5-engine pipeline. Zero revenue.

The non-trading infrastructure is enterprise-grade and completely untested against the only metric that matters: will someone pay for this?

## The Solution: Three Concurrent Revenue Paths

### Path A — Digital Product (FASTEST: hours to deploy)

**Product:** The Agentic Trading Blueprint
**Price:** $49
**Platform:** Gumroad (5-minute setup, no infrastructure needed)
**Landing page:** `/blueprint/` (BUILT — in repo)

**Content source mapping:**

| Volume | Source Files | Est. Pages | Redaction Needed |
|--------|-------------|-----------|-----------------|
| Vol 1: System Architecture | flywheel_strategy.md, COMMAND_NODE.md | 40-50 | VPS paths, SSH keys, wallet addresses |
| Vol 2: Edge Discovery Pipeline | edge_discovery_system.md, dispatches/ | 40-50 | Calibration params, exact thresholds |
| Vol 3: Strategy Compendium | edge_backlog_ranked.md | 60-80 | Live edge params, market IDs |
| Vol 4: Research Operations | karpathy_autoresearch_report.md, dispatches/ | 20-30 | Internal benchmarks, tool paths |

**To deploy TODAY:**

1. Go to gumroad.com → Create account → New Product
2. Name: "The Agentic Trading Blueprint"
3. Price: $49
4. Description: Copy from `/blueprint/index.html` hero section
5. Upload: Even a preview PDF with Vol 1 table of contents + first chapter is enough to start
6. Copy the Gumroad product URL
7. Replace `https://bradleyhaven.gumroad.com/l/agentic-trading-blueprint` in `/blueprint/index.html`
8. Deploy to Replit
9. Post to: HN (Show HN), Reddit r/algotrading, Twitter/X

### Path B — Consulting (FAST: 1-2 days to first booking)

**Product:** Architecture Review ($200/45min) and Strategy Deep-Dive ($350/60min)
**Platform:** Calendly (free tier) + Stripe Payment Link
**Landing page:** `/consult/` (BUILT — in repo)

**To deploy TODAY:**

1. Go to calendly.com → Create free account
2. Create event type: "Architecture Review — 45 min" and "Strategy Deep-Dive — 60 min"
3. Go to Stripe Dashboard → Payment Links → Create
4. Create two payment links ($200 and $350)
5. In Calendly, add redirect after booking to Stripe payment link OR add payment integration directly
6. Replace `YOUR_CALENDLY_LINK_HERE` in `/consult/index.html`
7. Deploy to Replit

### Path C — Website Growth Audit (MEDIUM: 2-4 weeks to first close)

**Product:** Website audit for SMBs ($500-$2,500)
**Status:** All infrastructure built, 10 prospects staged
**Landing page:** Already on `/leaderboards/worker/`

**To deploy (manual close path, no automation needed):**

1. Load staged prospects from `reports/nontrading/revenue_audit_launch_batch_seed.json`
2. Send personalized outreach from personal email (templates in `nontrading/email/templates/`)
3. Create Stripe Payment Link for $500 starter tier
4. Deliver audit manually using detection code in `nontrading/revenue_audit/`
5. Iterate based on feedback

---

## The John Bradley Action Checklist

### TODAY (30 minutes total)

- [ ] Create Gumroad account and product listing ($49, The Agentic Trading Blueprint)
- [ ] Create Calendly account with two event types
- [ ] Create two Stripe Payment Links ($200 architecture, $350 deep-dive)
- [ ] Replace placeholder URLs in `/blueprint/index.html` and `/consult/index.html`
- [ ] `git add blueprint/ consult/ FIRST_DOLLAR_PLAYBOOK.md`
- [ ] `git commit -m "Add Blueprint and Consult revenue pages"`
- [ ] Deploy to Replit

### THIS WEEKEND (2-3 hours total)

- [ ] Write Vol 1 Chapter 1 draft (the agent-run company frame — mostly exists in CLAUDE.md and flywheel_strategy.md)
- [ ] Create a preview PDF with table of contents + Chapter 1
- [ ] Upload to Gumroad as the initial product (update later with full content)
- [ ] Post "Show HN: I built an agent-run trading fund. Here's what I learned." to Hacker News
- [ ] Cross-post to r/algotrading, r/quantfinance, r/artificial

### NEXT WEEK

- [ ] Write remaining chapters (most content already exists in docs, needs editing + redaction)
- [ ] Begin manual outreach to 10 Website Growth Audit prospects
- [ ] Track: which path gets the first dollar?

---

## Why This Order

Path A (digital product) is fastest because:
- Zero marginal cost per sale
- No sales cycle — buy button on a page
- Content already exists in the repo (editing + redaction, not writing from scratch)
- Natural audience exists (HN, Reddit algo trading, crypto Twitter)
- The public repo + live P&L is the credential

Path B (consulting) is second because:
- Higher per-unit revenue ($200-350 vs $49)
- But requires scheduling, time commitment, and individual delivery
- Each session is proof of expertise that feeds Path A content

Path C (website audit) is longest because:
- Cold outreach sales cycle is 2-4 weeks minimum
- Requires fulfillment infrastructure (partially built)
- But highest recurring revenue potential

**The right move is to run all three simultaneously.** A and B generate revenue and credibility while C builds the repeatable business.

---

## Revenue Projections (Honest)

| Path | Time to $1 | 30-day target | 90-day target |
|------|-----------|--------------|--------------|
| A: Blueprint | 1-7 days | $500-2,000 | $5,000-15,000 |
| B: Consulting | 3-14 days | $400-1,400 | $2,000-7,000 |
| C: Website Audit | 14-30 days | $0-500 | $1,500-7,500 |
| **Combined** | **1-7 days** | **$900-3,900** | **$8,500-29,500** |

These are wide ranges because we have zero historical data on conversion rates. The Blueprint range depends entirely on distribution (one viral HN post = high end; no traction = low end). But even the low end of Path A alone gets us to first dollar within a week.

---

*This playbook was generated by JJ-N analysis of the complete Elastifund non-trading codebase. The infrastructure is impressive. The revenue is zero. Ship something today.*
