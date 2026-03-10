# REPLIT_NEXT_BUILD

Canonical build spec for the current static Elastifund website.

Last updated: 2026-03-10
Site URL: https://elastifund.replit.app
Companion artifact: `REPLIT_WEBSITE_CURRENT.pdf`

## Build decision

This pass keeps the current static root build.

- Do not migrate to full Next.js in this pass.
- Keep `index.html`, route directories, `site.js`, and `site.css` as the production website surface.
- Add `/live/` now.
- Keep `/elastic/` as the one dedicated Elastic page for this pass.
- `/elastic/` is for Elastic employees first and leadership-compatible readers second.
- `/live/` must read sanitized checked-in artifacts only.
- Browser access to Elastic-direct data stays out of scope.

This file is the single source of truth for the next website build. If the site changes, update this file first or in the same patch.

## Current site audit

### Problems the prior site had

- The homepage led with blocked-posture language instead of current proof.
- The dedicated BTC5 sleeve was underplayed even though it had real live-filled evidence.
- The trading page read like the whole system was inert.
- `/leaderboards/worker/` was still a definitions-only stub.
- There was no `/live/` route.
- The browser still depended on stale literals and fallback-heavy metrics.
- `REPLIT_NEXT_BUILD.md` described direction, but not an enforceable route-by-route build contract.

### Current repo truth the site must surface

- Broad runtime posture is still blocked.
- Fund-level realized ARR remains blocked while ledger and wallet reconciliation are unresolved.
- The dedicated BTC5 sleeve is the current public trading proof surface.
- Current checked-in BTC5 sleeve evidence:
  - `123` live-filled rows
  - `$108.86` live-filled PnL
  - source `remote_sqlite_probe`
- Current checked-in public ARR disclosure story from `improvement_velocity.json`:
  - conservative public forecast ARR headline `4,000%+`
  - raw selected forecast ARR `3,922,437.7%`
  - raw best-package forecast ARR `5,900,647.8%`
  - raw P05 forecast ARR `2,071,257.6%`
  - deploy recommendation `promote`
  - confidence `high`
  - selected source `reports/btc5_autoresearch_loop/latest.json`
- Current sleeve-only realized run-rate story from `improvement_velocity.json`:
  - trailing `12` live fills
  - `4.83` hour window
  - `+$2.79` sleeve-window PnL
  - `20,196.0%` sleeve-only annualized run rate
- Current timebound velocity story:
  - `9` cycles in the tracked window
  - `18.01` hour window
  - `+1,978,210.1%` forecast ARR gain
  - `+77` validation live-filled rows
- Current live shape still worth surfacing:
  - best direction `DOWN`
  - best direction PnL `+$89.46`
  - best price bucket `<0.49`
  - best price bucket PnL `+$50.90`
- JJ-N is real but still pre-launch:
  - first wedge is the Website Growth Audit
  - live send, checkout, fulfillment reporting, and revenue claims remain blocked
  - public-safe funnel counts are still zero until a real approval-cleared cycle exists

## Elastic employee route contract

`/elastic/` remains the dedicated Elastic route. Do not create a second employee page or a parallel partner-only Elastic page in this pass.

### Audience statement

- Elastic employees first
- leadership-compatible second
- assume readers care about Search AI, system memory, agent observability, evaluation, workflow automation, and hands-on contribution paths

### Route objective

- Prove Elastic as the best substrate for agentic AI in this repo.
- Do not frame Elastic as an observability add-on attached to a separate product story.
- Show how trading workers, JJ-N, evaluation, and public publishing all become legible because they share one Elastic-backed evidence layer.
- Keep browser reads on sanitized checked-in artifacts only; no direct Elastic browser access is part of this route.

## Implementation direction for this pass

### Explicit choice

- Keep the current static root build.
- Do not build `site/` or App Router pages in this pass.
- Use shared `site.js` and `site.css`.
- Use checked-in JSON artifacts for runtime, forecast, verification, and JJ-N surfaces.
- Add `/live/` as the public dashboard route now.

### Deferred work

- Full Next.js migration
- Server-side API routes for live data
- Elastic-backed browser reads
- Search, replay episodes, and incident streams

## Source artifacts the site is allowed to trust

These are the only primary sources the public site should read directly in this pass.

| Artifact | Role | Notes |
|---|---|---|
| `reports/public_runtime_snapshot.json` | primary public runtime snapshot | homepage, trading board, and `/live/` should prefer this |
| `reports/runtime_truth_latest.json` | deeper runtime detail and BTC5 provenance | fallback and detail source |
| `reports/remote_cycle_status.json` | launch posture and next operator action | use for blocked/next-action messaging |
| `reports/root_test_status.json` | verification headline | use checked-in summary only |
| `improvement_velocity.json` | BTC5 scoreboard, forecast, confidence, timebound velocity | primary performance-story artifact |
| `jjn_public_report.json` | JJ-N public-safe board | Phase 0 board and funnel zeros |
| `inventory/data/systems.json` | benchmarked system count | secondary proof surface |
| `reports/arb_empirical_snapshot.json` | A-6 and B-1 gate detail | trading board support |

### Artifact chaining allowed

These paths may be read only if they are referenced by an allowed primary artifact above:

- `latest_pipeline.path`
- `latest_edge_scan.path`
- detailed pipeline JSON referenced from `evidence_paths`

### Artifact trust rules

- Prefer artifact timestamps over prose timestamps.
- Prefer checked-in JSON over hand-written README summaries.
- Do not infer a metric that is not explicitly published.
- Do not blend trading, paper, forecast, and non-trading metrics into one headline number.

## Metrics contract

### Trading proof contract

| Public label | Source field | Rule |
|---|---|---|
| `current_system_arr` | `scoreboard.fund_realized_arr_pct` or `0` | show as realized only; stays blocked if claim status is blocked |
| `fund_claim_status` | `scoreboard.fund_realized_arr_claim_status` | must be rendered explicitly |
| `fund_claim_reason` | `scoreboard.fund_realized_arr_claim_reason` | must appear anywhere a fund claim is referenced |
| `btc5_live_pnl` | `scoreboard.btc5_live_filled_pnl_usd_total` or runtime/maker fallback | dedicated sleeve proof only |
| `btc5_live_rows` | `scoreboard.btc5_live_filled_rows_total` or runtime/maker fallback | dedicated sleeve proof only |
| `btc5_run_rate` | `scoreboard.realized_btc5_sleeve_run_rate_pct` | label as sleeve-only annualized run rate |
| `btc5_window_fills` | `scoreboard.realized_btc5_sleeve_window_live_fills` | show beside run rate |
| `btc5_window_hours` | `scoreboard.realized_btc5_sleeve_window_hours` | show beside run rate |
| `btc5_window_pnl` | `scoreboard.realized_btc5_sleeve_window_pnl_usd` | show beside run rate |
| `public_forecast_arr` | `scoreboard.public_forecast_arr_pct` | use for homepage and hero headline |
| `public_forecast_arr_label` | `scoreboard.public_forecast_arr_label` | preferred display string for hero and cards |
| `public_forecast_arr_cap_applied` | `scoreboard.public_forecast_arr_cap_applied` | if true, explain that public claims are conservatively capped |
| `public_forecast_arr_methodology` | `scoreboard.public_forecast_arr_methodology` | show near the headline or artifact ledger |
| `forecast_arr` | `scoreboard.active_forecast_arr_pct` | label as raw simulated or raw forecast |
| `forecast_best_arr` | `scoreboard.best_package_forecast_arr_pct` | optional support metric |
| `forecast_delta` | `scoreboard.forecast_arr_delta_pct` | optional support metric |
| `forecast_p05_arr` | `scoreboard.p05_forecast_arr_pct` | optional downside-aware support metric |
| `forecast_confidence` | `scoreboard.forecast_confidence_label` | must show |
| `forecast_confidence_reasons` | `scoreboard.forecast_confidence_reasons` | must show |
| `deploy_recommendation` | `scoreboard.deploy_recommendation` | may be shown; do not imply automatic deployment |
| `forecast_source` | `scoreboard.public_forecast_source_artifact` | must show on trading or `/live/` surfaces |
| `velocity_gain` | `timebound_velocity.forecast_arr_gain_pct` | label as forecast velocity, not realized performance |
| `velocity_per_day` | `timebound_velocity.forecast_arr_gain_pct_per_day` | same rule |
| `velocity_cycles` | `timebound_velocity.cycles_in_window` | support metric |
| `velocity_window_hours` | `timebound_velocity.window_hours` | support metric |
| `velocity_fill_growth` | `timebound_velocity.validation_fill_growth` | support metric |

### Runtime posture contract

| Public label | Source field | Rule |
|---|---|---|
| `runtime_split_summary` | derived from service status + launch posture + BTC5 sleeve visibility | must explicitly separate broad runtime and sleeve |
| `launch_posture` | `launch.live_launch_blocked` | show as blocked or clear |
| `next_action` | `launch.next_operator_action` | operator-facing copy only |
| `verification_summary` | `reports/root_test_status.json.summary` | do not paraphrase if the artifact exists |
| `btc5_source_label` | `runtime.btc5_source` or `btc_5min_maker.source` | surface provenance |
| `btc5_latest_fill` | `btc_5min_maker.latest_live_filled_at` | surface freshness |
| `btc5_guardrails` | `runtime.btc5_guardrail_recommendation` or maker fallback | label as recommendation |

### JJ-N contract

| Public label | Source field | Rule |
|---|---|---|
| `jjn_claim_status` | `jjn_public_report.json.claim_status` | must be shown |
| `jjn_claim_reason` | `jjn_public_report.json.claim_reason` | must be shown near the worker board hero or `/live/` |
| `jjn_offer_name` | `jjn_public_report.json.offer.name` | use the Website Growth Audit |
| `jjn_offer_price` | `jjn_public_report.json.offer.price_range_usd` | optional support metric |
| `jjn_offer_delivery` | `jjn_public_report.json.offer.delivery_days` | optional support metric |
| `jjn_approval_mode` | `jjn_public_report.json.activation.approval_mode` | must stay explicit |
| `jjn_send_status` | `jjn_public_report.json.activation.send_status` | must stay explicit |
| `jjn_fulfillment_status` | `jjn_public_report.json.activation.fulfillment_status` | must stay explicit |
| `jjn_accounts_researched` through `jjn_time_to_first_dollar` | `jjn_public_report.json.funnel.*` | zeros are valid and should remain visible until real data exists |

## Copy rules

### Required framing

- Lead with current proof, not generic philosophy.
- Use the dedicated BTC5 sleeve as the public trading proof surface.
- Keep fund-level realized ARR blocked until reconciliation is closed.
- Lead the homepage and `/live/` hero with the conservative `4,000%+` public BTC5 forecast ARR headline from `improvement_velocity.json`.
- Keep the raw selected forecast, best-package forecast, and sleeve-only run-rate visible beneath the conservative headline.
- Keep forecast language explicitly labeled as simulated, forecast, or sleeve-only annualized run rate.
- Keep JJ-N framed as a real wedge in launch prep, not a fictional revenue engine.
- Keep contributor, operator, and partner paths visible from the homepage.

### Forbidden framing

- No fake fund-level ARR.
- No blended trading plus non-trading revenue headline.
- No unlabeled simulated metric presented as realized.
- No raw multi-million-percent machine forecast as the only hero number.
- No "autonomous money machine" framing.
- No claims that browser users can see Elastic-direct live data in this pass.
- No fake screenshots or invented Elastic product UI presented as current proof.
- No copy that implies live browser reads from Elasticsearch, Kibana, APM, or any internal Elastic surface.

### Terminology rules

- Use `self-improving`, not `self-modifying`.
- Use `policy-governed autonomy`, not `remove the human from the loop`.
- Use `evidence`, `proof`, `artifact`, `forecast`, `blocked`, and `launch prep`.
- Use the compass artifact only to sharpen `/elastic/` employee-facing narrative and leadership-compatible summary.
- Do not use the compass artifact for trading performance claims.

## Design direction

Keep the existing family, but make it sharper.

- Typography: editorial serif for claims, mono for metrics and labels.
- Layout: denser proof cards, tighter metrics, stronger hero hierarchy.
- Visual split: always separate `live now`, `forecast`, and `building next`.
- Freshness: every primary proof surface gets a visible freshness badge.
- Energy: use stronger gradients, contrast, and rhythm, but keep the tone operator-grade.
- Avoid dark-terminal parody and avoid generic SaaS feature-box sameness.

## Route inventory

| Route | Purpose | Primary allowed sources |
|---|---|---|
| `/` | homepage proof surface | runtime snapshot, improvement velocity, JJ-N public report |
| `/live/` | checked-in dashboard | runtime snapshot, remote cycle status, root test status, improvement velocity, JJ-N public report |
| `/leaderboards/trading/` | trading proof board | runtime snapshot, runtime truth, improvement velocity, arb snapshot, pipeline/edge scan |
| `/leaderboards/worker/` | JJ-N Phase 0 board | JJ-N public report |
| `/elastic/` | Elastic employee landing page with leadership-compatible framing | homepage/runtime surfaces plus product narrative and public-scope guardrails |
| `/develop/` | contributor onboarding | runtime snapshot, root test status, shared repo commands |
| `/manage/`, `/diary/`, `/roadmap/`, `/docs/` | secondary static routes | may inherit shared status fills, but must not contradict the primary routes |

## Route-by-route acceptance criteria

### `/`

- Hero must lead with live BTC5 sleeve proof.
- Above the fold must include:
  - conservative public ARR headline panel
  - trading proof panel
  - timebound velocity panel
  - JJ-N wedge panel
  - contribution path panel
- Must state that fund-level realized ARR is blocked.
- Must show both the conservative `4,000%+` headline and the raw selected BTC5 forecast with clear labels.
- Must show freshness badges for snapshot, BTC5, forecast, and JJ-N.

### `/live/`

- Must exist.
- Must state that it reads checked-in artifacts only.
- Must show runtime posture, BTC5 proof, conservative public ARR headline, raw forecast confidence, JJ-N summary, and verification.
- Must include an artifact ledger explaining what is trusted.

### `/leaderboards/trading/`

- Must explicitly separate:
  - blocked fund-level realized claim
  - conservative public ARR headline
  - sleeve-only realized run rate
  - raw simulated forecast
- Must show BTC5 provenance and current guardrail recommendation.
- Must no longer imply that the whole trading system is inert.

### `/leaderboards/worker/`

- Must no longer be a pure stub.
- Must show the Website Growth Audit wedge explicitly.
- Must show approval mode, send status, fulfillment status, and honest funnel zeros.
- Must keep revenue and margin at zero until a real published cycle exists.

### `/elastic/`

Audience:

- Elastic employees first.
- Leadership-compatible second.
- Write for readers who care about Search AI, agent workflows, observability, evaluation, and contribution paths.

Route objective:

- Prove Elastic as the best substrate for agentic AI in Elastifund.
- Make it obvious that Elastic is not just a dashboard layer or observability add-on.
- Keep trading as one proof lane, not the whole story.

Required sections:

- Hero and subhead that keep the current system-memory line but make the first screen directly relevant to an Elastic employee.
- `Why Elastic is the fit for agentic AI` built around search, context engineering, observability, evaluation, and workflow control.
- `What Elastic does inside Elastifund today` with concrete public-safe surfaces: searchable artifacts, telemetry, traces, ML or anomaly jobs, operator dashboards, and the public publishing loop.
- Architecture diagram with Elastic visually in the middle between worker families, evidence or evaluation, and publishing surfaces.
- `What an employee can learn or contribute` with clear paths into the repo, `/live/`, `/develop/`, and `docs/ELASTIC_INTEGRATION.md`.
- `Paper mode, safety, and public scope` covering checked-in artifacts only, blocked-claim discipline, and no direct browser-side Elastic access.

CTA hierarchy:

1. Primary CTA: `/live/` as the checked-in proof board.
2. Secondary CTA: GitHub repo and `docs/ELASTIC_INTEGRATION.md` for technical inspection.
3. Tertiary CTA: `/develop/` for contribution and paper-mode-safe build paths.
4. Any trading-specific CTA must stay below the broader agentic-AI substrate story.

Proof labels:

- Must label checked-in artifacts, public-safe evidence, blocked claims, paper mode where applicable, and no direct Elastic browser reads.
- Must distinguish current public proof from future or internal Elastic possibilities.
- Must keep performance labels separated from platform narrative labels.

Explicit prohibitions:

- No fake screenshots, fake Discover panes, fake Kibana dashboards, or mock browser reads.
- No copy or visuals implying that the `/elastic/` route is querying Elastic directly in the browser.
- No claim that the public site can inspect private or internal Elastic data in this pass.

Acceptance criteria:

- The first screen answers why an Elastic employee should care within seconds.
- The route explicitly names search, context engineering, observability, evaluation, and workflow control.
- The route shows what Elastic is doing in the repo today without relying on browser-side Elastic access.
- The architecture section places Elastic in the middle and feels like a standout evidence section, not another generic card grid.
- CTA order follows the hierarchy above.
- Proof labels remain visible anywhere artifacts, metrics, or operational claims appear.

### `/develop/`

- Must preserve the verified repo-root boot path.
- Must point contributors to `/live/` first.
- Must keep explicit paper-mode and escalation framing.

## Freshness and confidence rules

- Freshness badges:
  - green/fresh: under 1 hour
  - amber/aging: under 24 hours
  - red/stale: 24 hours or older
- `current_system_arr` remains claim-safe realized ARR only.
- `btc5_run_rate` is allowed only when labeled sleeve-only and annualized.
- `public_forecast_arr` is allowed as the headline only when it uses the checked-in conservative disclosure fields.
- `forecast_arr` is allowed only when labeled raw simulated or raw forecast.
- `forecast_confidence` must appear anywhere forecast ARR is featured.
- JJ-N revenue metrics remain zero or unset until the public report says otherwise.

## Mobile and desktop requirements

- Desktop hero must keep the proof story readable without scrolling through long prose first.
- Mobile hero must stack cleanly without hiding freshness badges or action buttons.
- Primary buttons should remain full-width on small screens.
- Proof cards and freshness badges must wrap cleanly on mobile.
- Tables must remain horizontally scrollable instead of collapsing into unreadable text.

## Deployment and verification checklist

Run these from the repo root after website changes:

```bash
python3 scripts/check_website_copy.py
node --check site.js
make hygiene
```

Manual route check before publish:

1. Open `/`, `/live/`, `/leaderboards/trading/`, `/leaderboards/worker/`, `/elastic/`, and `/develop/`.
2. Confirm the homepage leads with BTC5 proof, forecast velocity, JJ-N wedge, and contribution paths.
3. Confirm `/leaderboards/trading/` separates blocked fund claims from sleeve-only proof.
4. Confirm `/leaderboards/worker/` is a Phase 0 board, not a placeholder-only stub.
5. Confirm `/live/` exists and only references checked-in artifacts.
6. Confirm `/elastic/` reads like an Elastic-employee landing page, not a vague manifesto or generic partner page.
7. Confirm `/elastic/` does not imply direct browser access to Elastic data or show fake screenshots.
8. Confirm freshness badges render and claim labels are visible.

Post-deploy:

- Manually refresh `REPLIT_WEBSITE_CURRENT.pdf`.
- If any source artifact changes shape, update `site.js` and this file in the same patch.
