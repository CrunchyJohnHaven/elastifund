# REPLIT_NEXT_BUILD

> Canonical build instructions for the next iteration of elastifund.co.
> Companion file: `REPLIT_WEBSITE_CURRENT.pdf` (screenshot of the live site at time of last update).
> These two files are the only context needed to brief a build session. They are updated automatically.

Last updated: 2026-03-09
Site URL: https://elastifund.replit.app
GitHub: https://github.com/CrunchyJohnHaven/elastifund

---

## Cycle 2 runtime reconciliation shipped

This cycle did not migrate the site to `site/`. The live repo source is still the root `index.html`, and Cycle 2 refreshed that single-file site in place.

Delivered in the March 9, 2026 refresh:

- dual-state system-status card: remote service observed active at `2026-03-09T00:44:19Z`, launch posture still blocked
- public-safe fast-market verdict note: `REJECT ALL`
- public-safe edge snapshot counts: `75` fast markets observed (`29` 15m, `39` 5m, `7` 4h), `563` allowed neg-risk events in the repo audit, `57` qualified A-6 live-surface events, `0` executable opportunities, `0` B-1 deterministic pairs in `1,000` allowed markets
- freshness stamps for metrics, verification baseline, service-state check time, and build date
- current metrics: `$347.51` tracked capital, `71.2%` calibrated win rate with `68.5%` legacy label, current root verification `failing` (`1 failed, 870 passed`), `131` strategy catalog, `11` dispatch work-orders, `23` benchmarked systems, `6` primary + `1` anomaly signal lane
- a new March 9 build-diary entry recording the service/launch drift reconciliation and why uptime did not clear trading
- a strategy-section note clarifying that the published cards are a public subset, not the full canonical ledger
- homepage runtime/status surfaces now hydrate from `reports/public_runtime_snapshot.json` and the latest pipeline/scan artifacts instead of relying only on handwritten numbers

Still not delivered this cycle:

- no `site/` directory or Next.js scaffold yet
- no Elastic-backed `/live` page
- the broader scorecard still is not fully sourced from the public snapshot; only the runtime/status surfaces are artifact-driven today

---

## Current site state (from REPLIT_WEBSITE_CURRENT.pdf)

The live site is still a single `index.html` with a dark terminal aesthetic. After the March 9, 2026 refresh it contains:

- Hero with a launch-blocked banner, GitHub link, MIT license, and refreshed Cycle 2 metrics
- System-status card: service observed active on March 9, 2026, launch posture still blocked, `REJECT ALL` fast-market note, public-safe edge counts, freshness stamps, and repo-artifact hydration
- Scorecard: 131 strategies tracked, current root verification status, 11 dispatch work-orders, 71.2% calibrated win rate with 68.5% legacy label, 23 benchmarked systems, 6 primary + 1 anomaly signal lane, $347.51 tracked capital
- "What Is Elastifund" explainer with agent-run company model comparison table
- "How It Works Right Now" pipeline: SCAN → RANK → FILTER → SIZE → RESTART
- System architecture updated around current signal lanes, execution gates, and the active-service / blocked-launch split
- About John Bradley section, mission (20% to veteran suicide prevention), contact
- Strategy encyclopedia with a public-subset note explaining the difference between published cards and the full canonical catalog
- Build Diary: includes the March 9, 2026 drift-reconciliation entry plus prior reverse-chronological entries
- Education Center: 7 beginner topics, 5 intermediate topics, 6 advanced topics — each with TL;DR, 5-min explanation, and technical deep dive
- Research Library: 56 outputs across 8 categories with ID, title, category, priority, summary
- Footer/build stamp updated to March 9, 2026

## What the current site does well

- Strategy encyclopedia with full failure autopsies — nobody else publishes this
- Build diary with honest "What We Learned" sections — real credibility
- Education center with three depth levels — genuinely useful content
- Anti-hype tone throughout — no "revolutionary AI" language
- Research library with categorized outputs — shows the actual work

## What the current site lacks

- Only the runtime/status surface hydrates from repo artifacts; the broader scorecard is still static repo-backed content
- No Elastic-backed public `/live` surface yet
- No search — 57 pages of content with no way to find anything
- Elastic Stack visibility is still descriptive, not wired to real public telemetry reads
- Single-file HTML — no component reuse, no build pipeline, and too much manual content maintenance

---

## Elastic Stack integration already built (waiting to be surfaced)

These modules exist in the repo and are tested. The website explains the Elastic layer, but it still does not expose any of it through live public data.

### Trading telemetry (bot/elastic_client.py)
- Indexes to: `elastifund-trades`, `elastifund-signals`, `elastifund-kills`, `elastifund-orderbook`, `elastifund-latency`
- Dataclass events: TradeEvent, SignalEvent, KillEvent, OrderbookSnapshotEvent, LatencyEvent
- Async bulk writer, graceful degradation, health check

### Polymarket bot telemetry (polymarket-bot/src/telemetry/elastic.py)
- Indexes to: `elastifund-agents` (heartbeat), `elastifund-metrics` (cycle PnL, Sharpe), `elastifund-trades`
- Methods: upsert_agent_status(), emit_metrics(), emit_trade()

### APM instrumentation (bot/apm_setup.py)
- Traces signal-to-order critical path
- Custom spans for Polymarket API, Kalshi API, LLM calls, SQLite
- Metrics: signal_latency_ms, order_to_fill_ms, llm_response_ms

### ML anomaly detection (bot/elastic_ml_setup.py)
- 5 anomaly jobs: VPIN spikes, spread regime changes, OFI divergence, signal confidence drift, kill rule frequency
- Anomaly consumer (bot/anomaly_consumer.py) feeds back into trading as signal source #7

### Kibana dashboards (infra/kibana_dashboards/)
- 6 pre-built: trading_overview, signal_quality, kill_rule_monitor, orderbook_health, apm_dashboard, ml_anomaly_dashboard

### Infrastructure (infra/)
- docker-compose.elastic.yml: ES 8.15.5, Kibana, Filebeat, APM Server
- setup.sh: automated bootstrap with password generation and health checks
- filebeat.yml, apm-server.yml: production configs

### Tests
- 5 dedicated test suites covering client, bootstrap, instrumentation, ML, telemetry

---

## What the next build should change

> **Vision-aligned priorities (March 9, 2026).** The Elastic Vision Document and Platform Vision Document define Elastifund as an open, self-improving agentic operating system for real economic work — not a single trading bot. The site must reflect that broader product definition. Trading is one module. The non-trading revenue worker (JJ-N) is the new first-class front door. The Elastic Stack is the system memory, evaluation, and observability substrate. Every page answers: what is this, why does it exist, why Elastic, and how do I contribute.

### Priority 0: Implement the vision messaging system

The site must answer four questions immediately on every surface: (1) what is this, (2) why does it exist, (3) why Elastic, and (4) how do I contribute.

**Homepage rewrite:**
- Hero: "A self-improving agentic operating system for real economic work."
- Subhead: "Elastifund turns research, experiments, and execution into searchable evidence — so trading and non-trading agents can improve with every run."
- Four live-evidence blocks (performance, improvement velocity, code commits, feature forecast)
- Three paths: contributor / operator / partner

**/elastic landing page (NEW):**
- Hero: "Open-source agents need a system memory. Elastic is the Search AI platform that makes them reliable."
- Executive-safe language throughout — no "self-modifying binary," "human removed from loop," or "money machine"
- Why Elastic: system memory, evaluation, observability, vector search, workflow automation, open-source contribution
- Business case: flagship open-source Search AI reference architecture, employee learning path, reusable customer patterns, public scoreboard
- CTA: explore the repo, view the live dashboard

**/develop onboarding page (NEW):**
- One-command setup with default paper mode
- Three contributor modes: Observer (watch dashboards, read diary) → Runner (run locally in safe mode, contribute data) → Builder (propose code changes, run tests, open PRs)
- Architecture diagram, troubleshooting, contribution path

**Terminology enforcement across all pages:**
- "self-improving" not "self-modifying"
- "policy-governed autonomy" not "human removed from the loop"
- "agentic work" or "economic work" not "money machine"
- "evidence" and "benchmarks" not "promises"
- "run in paper mode by default" as trust-building phrase everywhere

### Priority 1: Automate the refreshed homepage metrics
Cycle 2 now hydrates the runtime/status surface from repo artifacts, but the snapshot contract is still incomplete. The next build should finish the job and remove the fallback chain:
- Export repo-backed public metrics into a snapshot artifact
- Keep service state and launch posture synchronized as separate fields
- Keep pipeline verdict and A-6 / B-1 gate status synchronized
- Preserve the 71.2% calibrated vs 68.5% legacy/uncalibrated distinction
- Keep current counts aligned: capital, verified tests, strategy catalog, dispatch work-orders, benchmarked systems, signal lanes, cycles completed, and public-safe edge scan counts

### Priority 2: Surface the Elastic layer
The strongest differentiator we have is that every claim is backed by telemetry. The site should show this.

**Add a `/live` page** powered by sanitized reads from Elastic:
- Agent heartbeat and operating mode from `elastifund-agents`
- Cycle-level metrics from `elastifund-metrics`
- Latest trade snapshots from `elastifund-trades`
- Current kill rule headroom
- Anomaly detection status

**Add freshness stamps** to every metric on the homepage:
- Show "last updated: X" with source pointer
- Color-code: green (< 1hr), amber (< 24hr), red (> 24hr)

**Add an "Observability" section** to the main site:
- What we monitor and why
- Which Elastic products we use (Elasticsearch, Kibana, APM, ML, Filebeat)
- Architecture diagram: Market Data → Signal Pipeline → Elastic → Dashboards + ML → Feedback

### Priority 3: Non-trading worker leaderboard and dashboard surfaces

**Add `/leaderboards/trading`:**
- Ranked by risk-adjusted metric, with filters by market domain
- Explicit separation: deterministic backtest episodes / paper trading campaigns / real-money campaigns (hard-gated with warning text)

**Add `/leaderboards/worker` (NEW):**
- Ranked by verified value created: accounts researched, qualified leads, messages sent and reply rate, meetings booked and show rate, proposals sent, pipeline value, revenue won, gross margin, time to first dollar, annualized contribution margin
- Confidence bands on all metrics

**Add `/manage` operator dashboard (NEW):**
- What your instance ran, what it found, what changed, what is waiting for approval

### Priority 4: Migrate from single HTML to Next.js
- Create `site/` directory with Next.js App Router
- Port strongest content from index.html into component pages
- Ingest `docs/website/` content into routed pages
- Static generation for durable content, server routes for live Elastic reads
- Browser never talks directly to Elasticsearch — server acts as sanitized gateway

### Priority 5: Moat features
- Strategy autopsy graph: index strategies into `elastifund-knowledge`, expose related failures
- Search: lexical + vector over all published content
- Replayable agent episodes: one decision end-to-end
- Incident ribbon: public-safe filtered stream of system events
- Benchmark observatory: `/benchmark`, `/benchmark/methodology`, `/benchmark/bots`

---

## Design direction

Do not rebuild the dark terminal page in a slightly nicer framework.

Target aesthetic: research terminal meets financial newspaper meets mission control.
- Typography: serious editorial serif for claims, sharp mono for metrics and system labels
- Layout: bold section breaks, dense evidence cards, real tables, timeline views
- Motion: restrained, used only for data reveal and timeline playback
- Tone: operator-grade, anti-hype, evidence-first
- Rule: if a page cannot answer "where did this claim come from?" it is not ready

---

## Recommended site architecture (vision-aligned)

```
site/
  app/
    page.tsx                        # Homepage — self-improving agentic OS hero
    elastic/page.tsx                # /elastic — executive and employee pitch
    develop/page.tsx                # /develop — one-command setup + contributor modes
    live/page.tsx                   # /live — Elastic-backed operator window
    leaderboards/
      trading/page.tsx              # /leaderboards/trading — strategy ranking + paper/live split
      worker/page.tsx               # /leaderboards/worker — non-trading funnel metrics
    manage/page.tsx                 # /manage — operator dashboard (instance runs, findings, approvals)
    benchmark/page.tsx              # Benchmark observatory
    benchmark/methodology/page.tsx
    benchmark/bots/page.tsx
    research/page.tsx               # Research library
    autopsies/[slug]/page.tsx       # Individual strategy autopsies
    learn/[slug]/page.tsx           # Education center articles
    diary/page.tsx                  # /diary — chronological experiment record
    roadmap/page.tsx                # /roadmap — forecasted features and checkpoints
    mission/page.tsx                # Veteran suicide prevention mission
    vision/page.tsx                 # Autonomous market operator thesis
    docs/page.tsx                   # /docs — canonical numbered documents index
    api/live/route.ts               # Sanitized Elastic reads
    api/search/route.ts             # Knowledge search
    api/freshness/route.ts          # Metric freshness data
    api/worker-metrics/route.ts     # Non-trading worker leaderboard data
  components/
  content/
  lib/
    elastic/                        # ES client (server-side only)
    content/                        # Markdown/content loaders
    benchmark/                      # Benchmark API client
    formatting/                     # Number formatting, timestamps
  public/
    snapshots/                      # Pre-generated JSON for static pages
```

### Vision-aligned route map

| Route | Primary audience | Primary job |
|---|---|---|
| `/` | Curious visitors, contributors, partners | Explain the project in one screen with live evidence |
| `/elastic` | Elastic leadership and employees | Make the business case for Elastic as the agentic substrate |
| `/develop` | New contributors | Reduce friction to zero — one-command setup in paper mode |
| `/leaderboards/trading` | Researchers, users, investors | Show trading evidence with live/paper separation |
| `/leaderboards/worker` | Operators, customers, contributors | Show non-trading evidence: funnel metrics and confidence bands |
| `/manage` | Operators and contributors | Show what your instance ran, found, improved, and is waiting for review |
| `/diary` | All audiences | Chronological experiment record |
| `/roadmap` | Contributors and partners | Forecasted features and checkpoints |
| `/docs` | Builders and technical evaluators | Index into the canonical numbered documents |

Runtime model:
- Static generation for durable content (autopsies, education, methodology)
- Scheduled snapshot export for public metrics (scripts/export_public_site_snapshot.py)
- Server routes for small number of live reads (heartbeat, latest trade, incident ribbon)
- Aggressive caching — Replit should not do expensive real-time aggregation on every request

---

## Content ingestion

### Static from repo
- `docs/website/` explainers, glossary, education pages
- Strategy autopsies (from Strategy Encyclopedia)
- Benchmark methodology
- Mission and donation language
- Autonomous market operator vision (`docs/website/autonomous-market-operators.md`)

### Generated from repo
- Strategy counts and status breakdown
- Benchmark summaries
- Latest research dispatch metadata
- Docs freshness metadata
- Selected KPI rollups

### Live from Elastic
- Current heartbeat and operating mode
- Most recent cycle telemetry
- Latest trade snapshots
- Incident ribbon (filtered for public safety)

---

## Market expansion story the next build should tell

The next build says clearly: Elastifund is an open platform for agentic work, with trading and non-trading workers sharing a common data, evaluation, and improvement layer.

**Product definition:** Elastifund is an open, self-improving platform for agentic capital allocation and agentic labor. Two families of workers share a common substrate:

- **Trading workers:** agents that research, simulate, rank, and optionally execute market strategies under policy. Prediction markets are phase one; the broader ambition is an autonomous market operator that can evaluate opportunities across a defined eligible universe.
- **Non-trading workers (JJ-N):** agents that create economic value through business development, research, services, operations, and customer acquisition. The first wedge is a revenue-operations worker for a single high-ticket service business.

**Shared substrate (six-layer architecture):**
1. Experience layer — human-facing surfaces (site, dashboards, leaderboards)
2. Control layer — policy, scheduling, approvals, budgets, permissions, autonomy levels
3. Worker layer — trading workers, revenue workers, research workers, coding workers
4. Evaluation layer — experiment scoring, leaderboards, confidence estimates, improvement velocity
5. Memory layer — leads, markets, prompts, outcomes, code diffs, templates, forecasts
6. Data and telemetry layer — events, logs, metrics, traces, costs, errors, artifacts

**Non-trading architecture (five-engine model):**
1. Account Intelligence Engine — find, enrich, and score targets
2. Outreach Engine — draft, queue, and send compliant messages
3. Interaction Engine — handle replies, scheduling, and meeting prep
4. Proposal Engine — turn discovery into scoped offers
5. Learning Engine — evaluate outcomes and revise playbooks

Framing rules:
- The default public story is broader than trading: Elastifund is an open platform for agentic work
- Trading is one optional module; the non-trading revenue worker is the first-class front door
- Describe "unbiased" allocation as neutral scoring inside an explicit eligible universe, not a vague claim to trade everything
- Do not imply equities are live now — present them as the next venue after broker, data, compliance, and execution adapters exist
- Publish from `docs/website/autonomous-market-operators.md`

---

## What must never be public

- API keys, wallet keys, credentials
- Internal cluster topology
- Private LLM prompts
- Account-level sizing logic
- Exact live calibration coefficients (A=0.5914, B=-0.3977 are already public in the PDF — that's fine, but future live coefficients may not be)
- Any field that weakens the private edge boundary

---

## Immediate next actions (in build order)

1. Build `/elastic` and homepage rewrite with vision-aligned messaging (Priority 0)
2. Build `/develop` onboarding page with one-command setup and three contributor modes
3. Build `scripts/export_public_site_snapshot.py` so the refreshed homepage metrics stop being manual
4. Stand up `site/` as a Next.js app on Replit with the full vision route map
5. Make `/live` the first Elastic-backed page
6. Build `/leaderboards/trading` and `/leaderboards/worker` with honest separation and definitions
7. Port strategy encyclopedia and education center into routed components
8. Move freshness stamps from static copy to generated snapshot metadata
9. Add observability section showing the Elastic architecture with live-safe data feeds
10. Build `/manage` operator dashboard
11. Turn benchmark API into a product surface

---

## Replit-specific notes

- Port forwarding: Kibana on 5601 (private), site on 443 (public)
- Memory: if Docker available, use 512MB ES heap; if not, use Elastic Cloud free tier as backend
- Secrets: ES_HOST, ES_PORT, ES_USER, ES_PASSWORD, APM_SERVER_URL via Replit Secrets
- The `.replit` config should run the Next.js dev server, not the trading bot
- Bot telemetry flows from Dublin VPS → Elastic Cloud → site reads (the bot does not run on Replit)

---

*This file and REPLIT_WEBSITE_CURRENT.pdf are the complete build brief. Nothing else is needed to start a build session. Both files are updated automatically when the repo changes.*
