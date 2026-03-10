# REPLIT_NEXT_BUILD

Canonical build spec for the current static Elastifund website.

Last updated: 2026-03-09
Site URL: https://elastifund.replit.app
Companion artifact: `REPLIT_WEBSITE_CURRENT.pdf`

## Build decision

This pass keeps the current static root build.

- Do not migrate to full Next.js in this pass.
- Keep `index.html`, route directories, `site.js`, and `site.css` as the production website surface.
- Add `/live/` now.
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
  - `51` live-filled rows
  - `$75.68` live-filled PnL
  - source `remote_sqlite_probe`
- Current checked-in public forecast story from `improvement_velocity.json`:
  - active forecast ARR `4,667,673.7%`
  - best forecast ARR `5,811,064.1%`
  - delta `1,143,390.4%`
  - deploy recommendation `promote`
  - confidence `high`
- Current timebound velocity story:
  - `7` cycles in the tracked window
  - `1.1` hour window
  - `+1,143,390.4%` forecast ARR gain
  - `+6` validation live-filled rows
- JJ-N is real but still pre-launch:
  - first wedge is the Website Growth Audit
  - live send, checkout, fulfillment reporting, and revenue claims remain blocked
  - public-safe funnel counts are still zero until a real approval-cleared cycle exists

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
| `forecast_arr` | `scoreboard.active_forecast_arr_pct` | label as simulated or forecast |
| `forecast_best_arr` | `scoreboard.best_package_forecast_arr_pct` | optional support metric |
| `forecast_delta` | `scoreboard.forecast_arr_delta_pct` | optional support metric |
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
- Keep forecast language explicitly labeled as simulated or forecast.
- Keep JJ-N framed as a real wedge in launch prep, not a fictional revenue engine.
- Keep contributor, operator, and partner paths visible from the homepage.

### Forbidden framing

- No fake fund-level ARR.
- No blended trading plus non-trading revenue headline.
- No unlabeled simulated metric presented as realized.
- No "autonomous money machine" framing.
- No claims that browser users can see Elastic-direct live data in this pass.

### Terminology rules

- Use `self-improving`, not `self-modifying`.
- Use `policy-governed autonomy`, not `remove the human from the loop`.
- Use `evidence`, `proof`, `artifact`, `forecast`, `blocked`, and `launch prep`.
- Use the compass artifact only to sharpen `/elastic/` and partner/executive narrative.
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
| `/elastic/` | partner and executive framing | homepage/runtime surfaces plus product narrative |
| `/develop/` | contributor onboarding | runtime snapshot, root test status, shared repo commands |
| `/manage/`, `/diary/`, `/roadmap/`, `/docs/` | secondary static routes | may inherit shared status fills, but must not contradict the primary routes |

## Route-by-route acceptance criteria

### `/`

- Hero must lead with live BTC5 sleeve proof.
- Above the fold must include:
  - trading proof panel
  - timebound velocity panel
  - JJ-N wedge panel
  - contribution path panel
- Must state that fund-level realized ARR is blocked.
- Must show freshness badges for snapshot, BTC5, forecast, and JJ-N.

### `/live/`

- Must exist.
- Must state that it reads checked-in artifacts only.
- Must show runtime posture, BTC5 proof, forecast confidence, JJ-N summary, and verification.
- Must include an artifact ledger explaining what is trusted.

### `/leaderboards/trading/`

- Must explicitly separate:
  - blocked fund-level realized claim
  - sleeve-only realized run rate
  - simulated forecast
- Must show BTC5 provenance and current guardrail recommendation.
- Must no longer imply that the whole trading system is inert.

### `/leaderboards/worker/`

- Must no longer be a pure stub.
- Must show the Website Growth Audit wedge explicitly.
- Must show approval mode, send status, fulfillment status, and honest funnel zeros.
- Must keep revenue and margin at zero until a real published cycle exists.

### `/elastic/`

- Must frame Elastic as system memory, evaluation, observability, and publishing substrate.
- Must sharpen the partner/executive case using the compass narrative.
- Must avoid using the compass artifact for performance claims.

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
- `forecast_arr` is allowed only when labeled simulated or forecast.
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
6. Confirm freshness badges render and claim labels are visible.

Post-deploy:

- Manually refresh `REPLIT_WEBSITE_CURRENT.pdf`.
- If any source artifact changes shape, update `site.js` and this file in the same patch.
