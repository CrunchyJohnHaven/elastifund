# Execute Instance #2 — Replit Website Build (Vision-Aligned)

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- Capital: $347.51 total ($247.51 Polymarket + $100 Kalshi)
- Strategies: 131 tracked (7 deployed, 6 building, 2 structural alpha, 10 rejected, 8 pre-rejected, 1 re-evaluating, 97 research)
- Tests: 1,278 total verified (871+22 root, 374 polymarket, 11 non-trading)
- Dispatches: 11 DISPATCH_* work-orders; 95 markdown files in `research/dispatches/`
- Signal sources: 7 (LLM Ensemble, LMSR, WalletFlow, CrossPlatformArb, VPIN/OFI, LeadLag, ElasticML)
- Service: `jj-live.service` active but 0 trades in 305 cycles — drift state
- Pipeline: REJECT ALL across 74 observed markets
- Edge thresholds: Now env-var configurable (JJ_YES_THRESHOLD, JJ_NO_THRESHOLD)
- Cycle: 2 — Structural Alpha & Microstructure Defense
- Wallet-flow: ready (80 scored wallets)

### VISION CONTEXT (MANDATORY)

The website must reflect Elastifund's product definition: "An open, self-improving agentic operating system for real economic work." Two worker families: trading workers + non-trading workers (JJ-N). Improvement is the product.

**Approved messaging:** "self-improving," "policy-governed autonomy," "agentic work," "economic work," "evidence," "benchmarks," "run in paper mode by default"

**Forbidden messaging:** "self-modifying binary," "remove the human from the loop," "agent swarm that makes money"

**Homepage hero:** "A self-improving agentic operating system for real economic work."
**/elastic hero:** "Open-source agents need a system memory. Elastic is the Search AI platform that makes them reliable."

---

## OBJECTIVE

Build the next iteration of the Replit website (https://elastifund.replit.app) with vision-aligned messaging, corrected metrics, new route stubs, and the JJ-N non-trading worker as a first-class front door.

## YOU OWN

`index.html`, `REPLIT_NEXT_BUILD.md`, any website source files, route stubs

## DO NOT TOUCH

`bot/`, `execution/`, `strategies/`, `signals/`, `src/`, `tests/`

## STEPS

1. Read `REPLIT_NEXT_BUILD.md` for the full build spec including Priority 0 messaging system and vision-aligned route map.

2. Read `research/elastic_vision_document.md` and `research/platform_vision_document.md` for product definition, six-layer architecture, five-engine non-trading model, and messaging requirements.

3. Read `CLAUDE.md` "Current State" and `PROJECT_INSTRUCTIONS.md` Section 2A for exact live numbers.

4. **Priority 0 — Messaging system enforcement:**
   - Rewrite homepage hero to: "A self-improving agentic operating system for real economic work."
   - Add product definition paragraph: two worker families, improvement is the product
   - Add approved/forbidden terminology checker (scan all copy before committing)
   - Create `/elastic` route stub with hero: "Open-source agents need a system memory..."

5. **Correct ALL stale metrics in `index.html`:**
   - Strategy count → 131
   - Test count → 1,278 total verified
   - Dispatch count → 95
   - Signal sources → 7
   - Capital → $347.51
   - Cycles completed → 305
   - Win rate → 71.2% calibrated (NO-only: 76.2%)
   - Daily loss cap → $5
   - Position size → $5
   - Server → Dublin VPS (AWS Lightsail eu-west-1)

6. **Add route stubs** per REPLIT_NEXT_BUILD.md vision architecture:
   - `/elastic` — Elastic integration story
   - `/develop` — contributor/developer landing
   - `/leaderboards/trading` — trading worker scoreboard
   - `/leaderboards/worker` — non-trading worker scoreboard (placeholder)
   - `/manage` — operations dashboard link
   - `/diary` — experiment diary
   - `/roadmap` — public roadmap
   - `/docs` — numbered governance docs (placeholder)

7. **Non-trading worker section:** Add JJ-N section with five-engine model overview (Account Intelligence → Outreach → Interaction → Proposal → Learning). Position as "first-class front door."

8. **System Status section:**
   - Service: Running (drift — 0 trades in 305 cycles)
   - Pipeline: REJECT ALL
   - Wallet-flow: Ready (80 scored wallets)
   - Next milestone: First live trade
   - Deploy blocker: release manifest path mismatch

9. Add latest build diary entry if one exists. Update footer timestamp.

10. If `reports/edge_scan_*.json` exists from Instance #1, surface opportunity count summary (no specific trade details — public site).

## VERIFICATION

```bash
# Open index.html in a browser or validate HTML
python3 -c "
with open('index.html') as f: content = f.read()
assert '1,278' in content or '1278' in content, 'Test count not updated'
assert '305' in content, 'Cycle count not updated'
assert 'self-improving' in content, 'Vision messaging missing'
assert 'self-modifying' not in content, 'Forbidden messaging found'
assert 'agent swarm' not in content, 'Forbidden messaging found'
print('All checks passed')
"
```

## HANDOFF

```
INSTANCE #2 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after for each metric corrected]
Routes added: [list]
Messaging compliance: [pass/fail + any violations found]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
