# Runtime Profile Contract

Instance 2 defines the checked-in threshold and launch-control contract for the trading runtime.

## Canonical Selector

- Primary selector: `JJ_RUNTIME_PROFILE`
- Checked-in profile files live under `config/runtime_profiles/`
- Fixed profile names for this cycle:
  - `blocked_safe`
  - `shadow_fast_flow`
  - `research_scan`

If `JJ_RUNTIME_PROFILE` is unset, the loader defaults to `blocked_safe`.

## Loader Surface

- Python module: `config.runtime_profile`
- Primary API:
  - `load_runtime_profile(...)`
  - `write_effective_runtime_profile(...)`
- CLI:

```bash
python3 -m config.runtime_profile --list
python3 -m config.runtime_profile --profile shadow_fast_flow --output reports/runtime_profile_effective.json
```

The dump file is the debugging handoff artifact for this lane:

- `reports/runtime_profile_effective.json`

## Required Sections

Every checked-in runtime profile must define these top-level sections:

1. `mode`
2. `feature_flags`
3. `risk_limits`
4. `market_filters`
5. `signal_thresholds`
6. `combinatorial_thresholds`
7. `microstructure_thresholds`

Current semantics:

- `mode`
  - `execution_mode`: `blocked`, `shadow`, or `research`
  - `paper_trading`: mirrors the legacy `PAPER_TRADING` switch
  - `allow_order_submission`: explicit gate for whether the runtime may place or simulate orders
  - `launch_gate`: `blocked`, `wallet_flow_ready`, or `none`
- `feature_flags`
  - lane toggles and fast-flow posture
  - A-6 / B-1 shadow/live flags stay here because they are binary gates, not numeric thresholds
- `risk_limits`
  - bankroll, Kelly, exposure, position, and cycle cadence knobs
- `market_filters`
  - resolution horizon, category floor, and per-category priority map
- `signal_thresholds`
  - YES / NO thresholds plus LMSR entry threshold
- `combinatorial_thresholds`
  - A-6 / B-1 numeric gates, stale-book limits, execution timeout, and arb budget caps
- `microstructure_thresholds`
  - VPIN and WebSocket defense knobs

## Legacy Override Policy

Checked-in profiles are canonical. Existing env keys remain temporary compatibility overrides so the runtime can migrate without a flag day.

Supported legacy overrides currently include:

- mode and lane flags:
  - `PAPER_TRADING`
  - `ENABLE_LLM_SIGNALS`
  - `ENABLE_WALLET_FLOW`
  - `ENABLE_LMSR`
  - `ENABLE_CROSS_PLATFORM_ARB`
  - `JJ_FAST_FLOW_ONLY`
  - `ENABLE_A6_SHADOW`
  - `ENABLE_A6_LIVE`
  - `ENABLE_B1_SHADOW`
  - `ENABLE_B1_LIVE`
  - `JJ_A6_EMBEDDED_SHADOW_SCANNER`
- risk and market filters:
  - `JJ_MAX_POSITION_USD`
  - `JJ_MAX_DAILY_LOSS_USD`
  - `JJ_MAX_EXPOSURE_PCT`
  - `JJ_KELLY_FRACTION`
  - `JJ_MAX_KELLY_FRACTION`
  - `JJ_SCAN_INTERVAL`
  - `JJ_MAX_OPEN_POSITIONS`
  - `JJ_MIN_EDGE`
  - `JJ_INITIAL_BANKROLL`
  - `JJ_MAX_RESOLUTION_HOURS`
  - `JJ_MIN_CATEGORY_PRIORITY`
  - `JJ_CAT_PRIORITY_*`
- signal thresholds:
  - `JJ_YES_THRESHOLD`
  - `JJ_NO_THRESHOLD`
  - `JJ_LMSR_THRESHOLD`
- combinatorial thresholds:
  - `JJ_A6_BUY_THRESHOLD`
  - `JJ_A6_UNWIND_THRESHOLD`
  - `JJ_B1_IMPLICATION_THRESHOLD`
  - `JJ_COMBINATORIAL_STALE_BOOK_MAX_AGE_SECONDS`
  - `JJ_COMBINATORIAL_FILL_TIMEOUT_SECONDS`
  - `JJ_COMBINATORIAL_FILL_TIMEOUT_MS` as a legacy alias
  - `JJ_COMBINATORIAL_CANCEL_REPLACE_COUNT`
  - `JJ_COMBINATORIAL_MAX_NOTIONAL_PER_LEG_USD`
  - `JJ_COMBINATORIAL_ARB_BUDGET_USD`
  - `JJ_COMBINATORIAL_MERGE_MIN_NOTIONAL_USD`
  - `JJ_COMBINATORIAL_PROMOTION_MIN_SIGNALS`
  - `JJ_COMBINATORIAL_REQUIRED_CAPTURE_RATE`
  - `JJ_COMBINATORIAL_REQUIRED_CLASSIFICATION_ACCURACY`
  - `JJ_COMBINATORIAL_MAX_FALSE_POSITIVE_RATE`
  - `JJ_COMBINATORIAL_MAX_CONSECUTIVE_ROLLBACKS`
  - `JJ_CONSTRAINT_ARB_DB_PATH`
  - `JJ_DEP_GRAPH_DB_PATH`
- microstructure thresholds:
  - `JJ_VPIN_BUCKET_SIZE`
  - `JJ_VPIN_WINDOW`
  - `JJ_VPIN_TOXIC_THRESHOLD`
  - `JJ_VPIN_SAFE_THRESHOLD`
  - `JJ_WS_HEARTBEAT_INTERVAL`
  - `JJ_WS_REST_POLL_INTERVAL`

Override precedence is:

1. explicit env override
2. checked-in profile value
3. dataclass default

For `JJ_COMBINATORIAL_FILL_TIMEOUT_*`, the canonical env key is `JJ_COMBINATORIAL_FILL_TIMEOUT_SECONDS`. If both the seconds and legacy milliseconds alias are set, the seconds key wins.

## Notes For Instance 3

- Use `load_runtime_profile()` as the single source for threshold, feature-flag, and launch-gate decisions.
- Do not keep scattered `os.environ.get(...)` reads for keys already covered by this contract.
- The effective dump artifact is intended for startup diagnostics and release validation, not for secrets.
