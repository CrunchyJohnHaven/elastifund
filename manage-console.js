(function () {
  const STORAGE_KEY = 'elastifund_manage_console_v1';
  const MODES = {
    repair: {
      label: 'Repair Truth',
      priority: 'Control-plane repair',
      core: 'Prioritize launch truth, reconciliation drift, and stale writers before any edge tuning or capital escalation.',
      stageWeights: { search: 0, evidence: 2, gate: 4, execution: 1, learning: 1 },
    },
    gate: {
      label: 'Tighten Gate',
      priority: 'Promotion discipline',
      core: 'Require better evidence before promotion, surface failing checks, and treat noisy wins as untrusted until the gate is clear.',
      stageWeights: { search: 0, evidence: 1, gate: 4, execution: 2, learning: 2 },
    },
    exploit: {
      label: 'Exploit Edge',
      priority: 'Edge exploitation',
      core: 'Assume the loop is healthy enough to harvest signal. Push attention toward proven buckets, faster fills, and concrete PnL recovery.',
      stageWeights: { search: 1, evidence: 1, gate: 1, execution: 4, learning: 3 },
    },
    explore: {
      label: 'Increase Exploration',
      priority: 'Search expansion',
      core: 'Push more hypotheses through the front of the loop while keeping the gate intact. Optimize for learning velocity, not cosmetic activity.',
      stageWeights: { search: 4, evidence: 1, gate: 1, execution: 1, learning: 3 },
    },
    observe: {
      label: 'Increase Observability',
      priority: 'Freshness and telemetry',
      core: 'Bias toward proving that data is current, loops are alive, and the system can reconstruct what it actually did.',
      stageWeights: { search: 1, evidence: 4, gate: 2, execution: 1, learning: 2 },
    },
  };
  const STAGES = ['search', 'evidence', 'gate', 'execution', 'learning'];
  const STAGE_LABELS = {
    search: 'Search',
    evidence: 'Evidence',
    gate: 'Gate',
    execution: 'Execution',
    learning: 'Learning',
  };
  const BLOCKED_LABELS = {
    service_not_running: 'service not running',
    no_closed_trades: 'no closed trades',
    no_deployed_capital: 'no deployed capital',
    a6_gate_blocked: 'A-6 blocked',
    b1_gate_blocked: 'B-1 blocked',
    flywheel_not_green: 'flywheel hold',
    root_tests_not_passing: 'verification not green',
    accounting_reconciliation_drift: 'accounting reconciliation drift',
    polymarket_capital_truth_drift: 'capital reconciliation drift',
    mode_alignment: 'mode alignment drift',
  };
  const POSTURE_HOLD_REASONS = new Set([
    'forecast_deploy_recommendation_conflict_requires_repair_branch',
    'control_posture_blocked_requires_repair_branch',
  ]);
  const CONTROL_FIELDS = [
    'profile',
    'yes_threshold',
    'no_threshold',
    'max_resolution_hours',
    'hourly_notional_budget_usd',
    'per_trade_cap_usd',
    'enable_polymarket',
    'enable_kalshi',
  ];

  if (document.body?.dataset?.page !== 'manage') {
    return;
  }

  let consoleState = loadConsoleState();
  let runtimeData = null;
  let operatorApiBase = null;
  let controlPlaneSocket = null;
  let controlPlaneReconnectTimer = null;
  let refreshInterval = null;

  document.addEventListener('DOMContentLoaded', () => {
    bindStaticEvents();
    connectControlPlaneSocket();
    refreshInterval = window.setInterval(() => {
      refreshConsole().catch(() => {});
    }, 10000);
    refreshConsole().catch((error) => {
      console.error(error);
      showToast('Console failed to load telemetry');
    });
    applyPanelFocusFromUrl();
  });

  async function refreshConsole() {
    runtimeData = deriveConsoleData(await fetchArtifacts(), consoleState);
    renderConsole(runtimeData, consoleState);
  }

  function loadConsoleState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return {
        guidanceMode: MODES[parsed.guidanceMode] ? parsed.guidanceMode : 'repair',
        focusStage: STAGES.includes(parsed.focusStage) ? parsed.focusStage : 'gate',
        directives: Array.isArray(parsed.directives) ? parsed.directives.slice(0, 16) : [],
      };
    } catch (_error) {
      return { guidanceMode: 'repair', focusStage: 'gate', directives: [] };
    }
  }

  function saveConsoleState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(consoleState));
  }

  function apiCandidates() {
    const candidates = [];
    if (window.location?.origin?.startsWith('http')) {
      candidates.push(window.location.origin);
    }
    candidates.push('http://127.0.0.1:8080', 'http://localhost:8080');
    return [...new Set(candidates)];
  }

  async function discoverOperatorApiBase(force = false) {
    if (operatorApiBase && !force) return operatorApiBase;
    for (const candidate of apiCandidates()) {
      try {
        const response = await fetch(`${candidate}/healthz`, { cache: 'no-store' });
        if (response.ok) {
          operatorApiBase = candidate;
          return operatorApiBase;
        }
      } catch (_error) {
        continue;
      }
    }
    operatorApiBase = null;
    return null;
  }

  async function fetchArtifacts() {
    const [
      publicSnapshot,
      runtimeTruth,
      remoteCycleStatus,
      rootTestStatus,
      velocity,
      stateImprovement,
      operatorConsole,
      controlPlane,
      autoresearch,
      validationCohort,
      filterEconomics,
      healthSnapshot,
      livePnl,
      policyFrontier,
      hypothesisLab,
    ] = await Promise.all([
      fetchJson('/reports/public_runtime_snapshot.json'),
      fetchJson('/reports/runtime_truth_latest.json'),
      fetchJson('/reports/remote_cycle_status.json'),
      fetchJson('/reports/root_test_status.json'),
      fetchJson('/improvement_velocity.json'),
      fetchJson('/reports/state_improvement_latest.json'),
      fetchOperatorConsole(),
      fetchControlPlaneState(),
      fetchJson('/reports/console_runtime/btc5_autoresearch/latest.json'),
      fetchJson('/reports/btc5_validation_cohort_latest.json'),
      fetchJson('/reports/btc5_filter_economics_latest.json'),
      fetchJson('/reports/btc5_health_latest.json'),
      fetchJson('/reports/live_pnl_scoreboard/latest.json'),
      fetchJson('/reports/btc5_market_policy_frontier/latest.json'),
      fetchJson('/reports/btc5_hypothesis_lab/summary.json'),
    ]);

    return {
      publicSnapshot,
      runtimeTruth,
      remoteCycleStatus,
      rootTestStatus,
      velocity,
      stateImprovement,
      operatorConsole: operatorConsole?.payload || null,
      operatorApiBase: operatorConsole?.apiBase || null,
      controlPlane: controlPlane?.payload || null,
      autoresearch,
      validationCohort,
      filterEconomics,
      healthSnapshot,
      livePnl,
      policyFrontier,
      hypothesisLab,
    };
  }

  async function fetchJson(path) {
    try {
      const response = await fetch(path, { cache: 'no-store' });
      if (!response.ok) return null;
      return response.json();
    } catch (_error) {
      return null;
    }
  }

  async function fetchOperatorConsole() {
    const apiBase = await discoverOperatorApiBase();
    if (!apiBase) {
      return { apiBase: null, payload: null };
    }
    try {
      const response = await fetch(`${apiBase}/api/v1/operator/console`, { cache: 'no-store' });
      if (!response.ok) {
        return { apiBase, payload: null };
      }
      return { apiBase, payload: await response.json() };
    } catch (_error) {
      operatorApiBase = null;
      return { apiBase: null, payload: null };
    }
  }

  async function fetchControlPlaneState() {
    const apiBase = await discoverOperatorApiBase();
    if (!apiBase) return { apiBase: null, payload: null };
    try {
      const response = await fetch(`${apiBase}/api/v1/control-plane/state`, { cache: 'no-store' });
      if (!response.ok) return { apiBase, payload: null };
      return { apiBase, payload: await response.json() };
    } catch (_error) {
      return { apiBase: null, payload: null };
    }
  }

  async function postOperatorJson(path, payload) {
    const apiBase = await discoverOperatorApiBase();
    if (!apiBase) {
      throw new Error('Hub API offline');
    }
    const response = await fetch(`${apiBase}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.detail || `Request failed (${response.status})`);
    }
    return body;
  }

  function controlPlaneWsUrl() {
    if (!operatorApiBase) return null;
    const url = new URL(operatorApiBase);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = '/ws/control-plane';
    url.search = '';
    return url.toString();
  }

  async function connectControlPlaneSocket() {
    await discoverOperatorApiBase();
    const wsUrl = controlPlaneWsUrl();
    if (!wsUrl || controlPlaneSocket) return;
    try {
      controlPlaneSocket = new WebSocket(wsUrl);
      controlPlaneSocket.addEventListener('message', () => {
        refreshConsole().catch(() => {});
      });
      controlPlaneSocket.addEventListener('close', () => {
        controlPlaneSocket = null;
        if (controlPlaneReconnectTimer) window.clearTimeout(controlPlaneReconnectTimer);
        controlPlaneReconnectTimer = window.setTimeout(() => {
          connectControlPlaneSocket().catch(() => {});
        }, 2000);
      });
      controlPlaneSocket.addEventListener('error', () => {
        controlPlaneSocket?.close();
      });
      controlPlaneSocket.addEventListener('open', () => {
        if (controlPlaneReconnectTimer) {
          window.clearTimeout(controlPlaneReconnectTimer);
          controlPlaneReconnectTimer = null;
        }
      });
    } catch (_error) {
      controlPlaneSocket = null;
    }
  }

  function pick(source, paths, fallback) {
    if (!source) return fallback;
    for (const path of paths) {
      const value = path.split('.').reduce((current, key) => {
        if (current && Object.prototype.hasOwnProperty.call(current, key)) {
          return current[key];
        }
        return undefined;
      }, source);
      if (value !== undefined && value !== null) return value;
    }
    return fallback;
  }

  function normalizeNumber(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function formatUsd(value, digits = 2) {
    const numeric = normalizeNumber(value, 0);
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(numeric);
  }

  function formatNumber(value, digits = 0) {
    const numeric = normalizeNumber(value, 0);
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(numeric);
  }

  function formatHours(value) {
    const numeric = normalizeNumber(value, 0);
    return numeric >= 10 ? numeric.toFixed(0) : numeric.toFixed(1);
  }

  function formatCompactPercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 'n/a';
    if (Math.abs(numeric) >= 100000) {
      return `${new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(numeric)}%`;
    }
    return `${formatNumber(numeric, 1)}%`;
  }

  function formatShortUtc(value) {
    if (!value) return 'unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'unknown';
    return `${new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC',
    }).format(date)} UTC`;
  }

  function formatRelativeAge(value) {
    if (!value) return { label: 'unknown', tone: 'bad', minutes: Number.POSITIVE_INFINITY };
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return { label: 'unknown', tone: 'bad', minutes: Number.POSITIVE_INFINITY };
    const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
    if (minutes < 60) return { label: `fresh ${minutes}m`, tone: 'good', minutes };
    if (minutes < 360) return { label: `aging ${formatHours(minutes / 60)}h`, tone: 'warn', minutes };
    return { label: `stale ${formatHours(minutes / 60)}h`, tone: 'bad', minutes };
  }

  function freshestTimestamp(...values) {
    return values
      .filter(Boolean)
      .map(value => ({ raw: value, ts: new Date(value).getTime() }))
      .filter(item => Number.isFinite(item.ts))
      .sort((left, right) => right.ts - left.ts)[0]?.raw || null;
  }

  function parseVerificationSummary(summary) {
    const failedMatch = /(\d+)\s+failed/.exec(summary || '');
    const passedMatches = Array.from((summary || '').matchAll(/(\d+)\s+passed/g));
    return {
      failed: failedMatch ? Number(failedMatch[1]) : 0,
      passed: passedMatches.reduce((sum, match) => sum + Number(match[1]), 0),
    };
  }

  function titleCase(value) {
    return String(value || '')
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, letter => letter.toUpperCase());
  }

  function humanizeBlockedChecks(checks) {
    return (checks || []).map(item => BLOCKED_LABELS[item] || item.replace(/_/g, ' '));
  }

  function summarizeList(values, maxItems = 2) {
    const items = (values || []).filter(Boolean);
    if (!items.length) return 'none';
    if (items.length <= maxItems) return items.join(', ');
    return `${items.slice(0, maxItems).join(', ')} +${items.length - maxItems}`;
  }

  function formatRatioPercent(value, digits = 1) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 'n/a';
    return `${formatNumber(numeric * 100, digits)}%`;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function compactCandidateName(value) {
    return titleCase(String(value || 'candidate').replace(/^baseline_/i, '').replace(/^current_live_/i, 'live_'));
  }

  function compactCandidateId(value) {
    return titleCase(
      String(value || 'candidate')
        .replace(/^btc5:/i, '')
        .replace(/^adjacent:/i, '')
        .replace(/^policy_/i, '')
        .replace(/__+/g, ' ')
        .replace(/[_:]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim(),
    );
  }

  function compactTradeSlug(value) {
    return String(value || 'window')
      .replace(/^btc-updown-5m-/, '')
      .replace(/^btc-/, '');
  }

  function frontierTone(point) {
    if (point.isSelected || point.action === 'promote') return 'good';
    if (point.action === 'hold') return 'warn';
    if (point.action === 'kill') return 'bad';
    return point.tone || 'neutral';
  }

  function toneForTradeStatus(status) {
    const normalized = String(status || '').toLowerCase();
    if (!normalized) return 'warn';
    if (normalized.includes('filled')) return 'good';
    if (normalized.startsWith('skip_')) return 'bad';
    if (normalized.includes('pending') || normalized.includes('open') || normalized.includes('reserved')) return 'warn';
    return 'warn';
  }

  function buildOverviewCard(tone, label, value, detail) {
    return { tone, label, value, detail };
  }

  function truncateText(value, maxLength = 88) {
    const text = String(value || '').trim();
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
  }

  function deriveConsoleData(artifacts, state) {
    const snapshot = artifacts.publicSnapshot || artifacts.runtimeTruth || artifacts.remoteCycleStatus || {};
    const detail = artifacts.runtimeTruth || artifacts.publicSnapshot || artifacts.remoteCycleStatus || {};
    const velocity = artifacts.velocity || {};
    const rootTestStatus = artifacts.rootTestStatus || {};
    const operatorConsole = artifacts.operatorConsole || {};
    const effectiveProfile = pick(operatorConsole, ['runtime_controls.effective_profile'], {});
    const latestGuidance = pick(operatorConsole, ['guidance.latest_packet'], {});
    const latestRuntimeControl = pick(operatorConsole, ['runtime_controls.latest_action'], {});
    const controlPlane = artifacts.controlPlane || {};
    const controlPlaneJobs = Array.isArray(controlPlane.jobs) ? controlPlane.jobs : [];
    const controlPlaneEvents = Array.isArray(controlPlane.events) ? controlPlane.events : [];
    const simulationState = pick(controlPlane, ['simulation'], {});
    const simulationLanes = Array.isArray(simulationState.lanes) ? simulationState.lanes : [];
    const simulationFindings = Array.isArray(simulationState.findings) ? simulationState.findings : [];
    const activeSimulationJobs = Array.isArray(simulationState.active_jobs) ? simulationState.active_jobs : [];
    const tradingData = pick(controlPlane, ['trading_data'], {});
    const recentTradeRows = Array.isArray(tradingData.recent_rows) ? tradingData.recent_rows : [];
    const autoresearch = artifacts.autoresearch || {};
    const stateImprovement = artifacts.stateImprovement || {};
    const validationCohort = artifacts.validationCohort || {};
    const filterEconomics = artifacts.filterEconomics || {};
    const healthSnapshot = artifacts.healthSnapshot || {};
    const livePnl = artifacts.livePnl || {};
    const policyFrontier = artifacts.policyFrontier || {};
    const hypothesisLab = artifacts.hypothesisLab || {};

    const runtime = pick(detail, ['runtime'], {});
    const service = pick(detail, ['service'], {});
    const launch = pick(detail, ['launch'], {});
    const maker = pick(detail, ['btc_5min_maker'], {});
    const scoreboard = pick(velocity, ['scoreboard'], {});
    const timebound = pick(velocity, ['timebound_velocity'], {});
    const contribution = pick(velocity, ['contribution_flywheel', 'velocity_metrics'], {});
    const tieOut = pick(velocity, ['polymarket_tie_out'], {});

    const launchBlocked = Boolean(pick(launch, ['live_launch_blocked'], true));
    const blockedChecks = Array.isArray(pick(launch, ['blocked_checks'], []))
      ? pick(launch, ['blocked_checks'], [])
      : [];
    const rawLaunchReasons = [
      ...blockedChecks,
      ...(Array.isArray(pick(detail, ['block_reasons'], [])) ? pick(detail, ['block_reasons'], []) : []),
      ...(Array.isArray(pick(launch, ['blocked_reasons'], [])) ? pick(launch, ['blocked_reasons'], []) : []),
    ].filter(Boolean);
    const structuralLaunchReasons = rawLaunchReasons.filter(reason => !POSTURE_HOLD_REASONS.has(String(reason)));
    const blockedReasons = humanizeBlockedChecks(structuralLaunchReasons);
    const launchRepairRequired = structuralLaunchReasons.length > 0;
    const selectedDeployRecommendation = String(
      pick(detail, ['btc5_selected_package.selected_deploy_recommendation'], 'unknown'),
    ).toLowerCase();
    const selectedPackageChecks = Array.isArray(pick(detail, ['btc5_selected_package.blocking_checks'], []))
      ? pick(detail, ['btc5_selected_package.blocking_checks'], [])
      : [];
    const promotionHold = launchBlocked && !launchRepairRequired;
    const verificationSummary = String(pick(rootTestStatus, ['summary'], pick(velocity, ['runtime_summary.verification_summary'], 'verification unavailable')));
    const verification = parseVerificationSummary(verificationSummary);
    const serviceActive = ['running', 'active'].includes(String(pick(service, ['status'], 'stopped')).toLowerCase());

    const generatedAt = pick(snapshot, ['generated_at'], pick(detail, ['generated_at'], pick(velocity, ['generated_at'], null)));
    const serviceCheckedAt = freshestTimestamp(
      pick(service, ['checked_at'], null),
      healthSnapshot.generated_at,
      generatedAt,
    );
    const latestFillAt = pick(maker, ['latest_live_filled_at'], pick(runtime, ['btc5_checked_at'], generatedAt));
    const latestTradingActivityAt = pick(tradingData, ['latest_activity_at'], null);
    const forecastAt = pick(timebound, ['window_ended_at'], pick(velocity, ['generated_at'], generatedAt));
    const snapshotFreshness = formatRelativeAge(generatedAt);
    const serviceFreshness = formatRelativeAge(serviceCheckedAt);
    const latestFillFreshness = formatRelativeAge(freshestTimestamp(latestTradingActivityAt, latestFillAt));
    const forecastFreshness = formatRelativeAge(forecastAt);
    const healthFreshness = formatRelativeAge(healthSnapshot.generated_at);
    const autoresearchFreshness = formatRelativeAge(autoresearch.generated_at || hypothesisLab.generated_at);

    const btc5LiveRows = normalizeNumber(pick(scoreboard, ['btc5_live_filled_rows_total'], pick(maker, ['live_filled_rows'], 0)), 0);
    const btc5LivePnl = normalizeNumber(pick(scoreboard, ['btc5_live_filled_pnl_usd_total'], pick(maker, ['live_filled_pnl_usd'], 0)), 0);
    const windowPnl = normalizeNumber(pick(scoreboard, ['realized_btc5_sleeve_window_pnl_usd'], 0), 0);
    const windowFills = normalizeNumber(pick(scoreboard, ['realized_btc5_sleeve_window_live_fills'], 0), 0);
    const windowHours = normalizeNumber(pick(scoreboard, ['realized_btc5_sleeve_window_hours'], 0), 0);
    const walletClosedPositions = normalizeNumber(pick(runtime, ['polymarket_closed_positions'], pick(detail, ['polymarket_wallet.closed_positions_count'], 0)), 0);
    const velocityCycles = normalizeNumber(pick(timebound, ['cycles_in_window'], 0), 0);
    const velocityWindowHours = normalizeNumber(pick(timebound, ['window_hours'], 0), 0);
    const velocityFillGrowth = normalizeNumber(pick(timebound, ['validation_fill_growth'], 0), 0);
    const trackedStrategies = normalizeNumber(pick(velocity, ['trading_agent.strategies_total'], 131), 131);
    const dispatchWorkOrders = normalizeNumber(pick(contribution, ['dispatch_work_orders'], 36), 36);
    const forecastTrendSeries = Array.isArray(pick(velocity, ['chart_series.forecast_arr_trend'], []))
      ? pick(velocity, ['chart_series.forecast_arr_trend'], []).map(point => ({
        active: normalizeNumber(point.active_forecast_arr_pct, 0),
        best: normalizeNumber(point.best_forecast_arr_pct, 0),
        fills: normalizeNumber(point.live_filled_rows, 0),
        timestamp: point.timestamp,
      }))
      : [];
    const launchBlockerSummary = summarizeList(blockedReasons, 2);
    const tieOutConflict = String(pick(tieOut, ['wallet_export_candidate_conflict_status'], '')).toLowerCase() === 'conflict';
    const tieOutStale = String(pick(tieOut, ['selected_wallet_reporting_freshness'], '')).toLowerCase() === 'stale';
    const etDay = pick(livePnl, ['et_day'], {});
    const rolling24h = pick(livePnl, ['rolling_24h'], {});
    const healthFlags = Array.isArray(healthSnapshot.alert_flags) ? healthSnapshot.alert_flags : [];
    const recentProbe = pick(autoresearch, ['current_probe'], {});
    const currentDecision = pick(autoresearch, ['decision'], {});
    const rankedPackages = Array.isArray(pick(autoresearch, ['ranked_runtime_packages'], []))
      ? pick(autoresearch, ['ranked_runtime_packages'], [])
      : [];
    const promotionCandidates = Array.isArray(pick(autoresearch, ['promotion_candidates'], []))
      ? pick(autoresearch, ['promotion_candidates'], [])
      : [];
    const policyRanks = Array.isArray(pick(policyFrontier, ['ranked_policies'], []))
      ? pick(policyFrontier, ['ranked_policies'], [])
      : [];
    const incumbentPolicyLoss = normalizeNumber(policyFrontier.incumbent_policy_loss, 0);
    const improvementMetrics = pick(stateImprovement, ['five_metric_scorecard.metrics'], pick(stateImprovement, ['metrics'], {}));
    const championLane = pick(stateImprovement, ['strategy_recommendations.btc5_candidate_recovery.champion_lane'], {});
    const improvementCandidateCount = normalizeNumber(pick(improvementMetrics, ['candidate_count'], pick(stateImprovement, ['per_venue_candidate_counts.total'], 0)), 0);
    const improvementConversion = normalizeNumber(
      pick(improvementMetrics, ['candidate_to_trade_conversion'], pick(stateImprovement, ['metrics.candidate_to_trade_conversion'], 0)),
      0,
    );
    const improvementExecutedNotional = normalizeNumber(
      pick(improvementMetrics, ['executed_notional_usd'], pick(stateImprovement, ['per_venue_executed_notional_usd.combined_hourly'], 0)),
      0,
    );
    const improvementResolvedPnl = normalizeNumber(
      pick(improvementMetrics, ['recent_resolved_pnl_usd'], pick(stateImprovement, ['strategy_recommendations.closed_cashflow_delta_1d'], 0)),
      0,
    );
    const championEdgeLabel = compactCandidateId(pick(championLane, ['top_candidate_id'], 'no champion'));
    const championEvidenceBand = String(pick(championLane, ['top_evidence_band'], 'unknown')).replace(/_/g, ' ');
    const championDeploymentClass = String(pick(championLane, ['top_deployment_class'], 'unclassified')).replace(/_/g, ' ');
    const championScore = normalizeNumber(pick(championLane, ['top_ranking_score'], 0), 0);
    const stateImprovementFreshness = formatRelativeAge(stateImprovement.generated_at);

    const frontierCandidates = (rankedPackages.length ? rankedPackages : promotionCandidates).slice(0, 6).map((item, index) => {
      const candidate = item.candidate || {};
      const profile = pick(candidate, ['profile'], {});
      const monteCarlo = pick(candidate, ['monte_carlo'], {});
      const historical = pick(candidate, ['historical'], {});
      const scoring = pick(candidate, ['scoring'], {});
      const decision = pick(item, ['decision'], {});
      const name = compactCandidateName(pick(profile, ['name'], pick(candidate, ['candidate_family'], `${item.source || 'candidate'}_${index + 1}`)));
      const profitProbability = normalizeNumber(
        pick(monteCarlo, ['profit_probability'], pick(monteCarlo, ['avg_win_rate'], 0)),
        0,
      );
      const drawdownUsd = normalizeNumber(
        pick(monteCarlo, ['p95_max_drawdown_usd'], pick(monteCarlo, ['avg_max_drawdown_usd'], 0)),
        0,
      );
      const fillCount = normalizeNumber(
        pick(scoring, ['validation_live_filled_rows'], pick(historical, ['replay_live_filled_rows'], pick(item, ['validation_live_filled_rows'], 0))),
        0,
      );
      const medianPnlUsd = normalizeNumber(
        pick(monteCarlo, ['median_total_pnl_usd'], pick(historical, ['replay_live_filled_pnl_usd'], 0)),
        0,
      );
      const p05PnlUsd = normalizeNumber(
        pick(monteCarlo, ['p05_total_pnl_usd'], pick(monteCarlo, ['mean_total_pnl_usd'], medianPnlUsd)),
        medianPnlUsd,
      );
      const action = String(pick(decision, ['action'], currentDecision.action || 'hold')).toLowerCase();
      const source = String(item.source || candidate.candidate_family || 'runtime');
      const isSelected = source === 'best_live_package' || name.toLowerCase().includes('active profile');
      return {
        id: `${source}-${name}-${index}`,
        name,
        source,
        action,
        tone: action === 'hold' ? 'warn' : action === 'promote' ? 'good' : 'neutral',
        isSelected,
        profitProbability,
        drawdownUsd,
        fillCount,
        medianPnlUsd,
        p05PnlUsd,
        liveExecutionScore: normalizeNumber(item.live_execution_score, 0),
        rawResearchScore: normalizeNumber(item.raw_research_score, 0),
      };
    });

    const policyBars = policyRanks.slice(0, 5).map((item, index) => {
      const improvement = normalizeNumber(incumbentPolicyLoss - normalizeNumber(item.policy_loss, incumbentPolicyLoss), 0);
      return {
        id: `${item.policy_id || 'policy'}-${index}`,
        name: compactCandidateName(item.policy_id || `policy_${index + 1}`),
        improvement,
        fillsPerDay: normalizeNumber(item.expected_fills_per_day, pick(item, ['fold_results.0.expected_fills_per_day'], 0)),
        confidenceLow: normalizeNumber(item.bootstrap_ci_low, 0),
        confidenceHigh: normalizeNumber(item.bootstrap_ci_high, 0),
      };
    });

    const directionBuckets = Array.isArray(pick(recentProbe, ['recent_direction_mix.buckets'], []))
      ? pick(recentProbe, ['recent_direction_mix.buckets'], [])
      : [];
    const priceBuckets = Array.isArray(pick(recentProbe, ['recent_price_bucket_mix.buckets'], []))
      ? pick(recentProbe, ['recent_price_bucket_mix.buckets'], [])
      : [];
    const byFilter = pick(filterEconomics, ['by_filter'], {});
    const checkpointMatch = /(\d+)\/(\d+)/.exec(String(validationCohort.checkpoint_status || ''));
    const cohortResolved = normalizeNumber(validationCohort.resolved_down_fills, checkpointMatch ? Number(checkpointMatch[1]) : 0);
    const cohortTarget = checkpointMatch ? Number(checkpointMatch[2]) : 50;
    const cohortProgress = cohortTarget > 0 ? cohortResolved / cohortTarget : 0;
    const rolling24hPnl = normalizeNumber(rolling24h.net_after_rebate_pnl_usd, normalizeNumber(livePnl.legacy_recent_pnl_usd, 0));
    const policySelection = pick(policyFrontier, ['selection_recommendation'], {});

    const stageStatus = {
      search: {
        tone: autoresearchFreshness.tone === 'good' ? 'good' : autoresearchFreshness.tone === 'warn' ? 'warn' : 'bad',
        meta: `${autoresearchFreshness.label} probe / ${formatNumber(recentProbe.recent_window_rows || trackedStrategies)} rows`,
      },
      evidence: {
        tone: !serviceActive || snapshotFreshness.tone === 'bad' || serviceFreshness.tone === 'bad' || healthFreshness.tone === 'bad'
          ? 'bad'
          : snapshotFreshness.tone === 'warn' || serviceFreshness.tone === 'warn' || healthFreshness.tone === 'warn'
            ? 'warn'
            : 'good',
        meta: `${snapshotFreshness.label} snapshot / ${healthFreshness.label} health`,
      },
      gate: {
        tone: launchRepairRequired || verification.failed > 0 ? 'bad' : promotionHold ? 'warn' : 'good',
        meta: launchRepairRequired
          ? launchBlockerSummary
          : promotionHold
            ? `shadow hold · ${selectedDeployRecommendation || 'hold'}`
            : verification.failed > 0
              ? `${verification.failed} tests failing`
              : 'launch clear',
      },
      execution: {
        tone: !serviceActive || btc5LiveRows === 0 ? 'bad' : btc5LivePnl < 0 || latestFillFreshness.tone !== 'good' || healthFlags.length ? 'warn' : 'good',
        meta: `${formatNumber(btc5LiveRows)} rows / ${formatUsd(btc5LivePnl)} / ${healthFlags[0] || 'clean'}`,
      },
      learning: {
        tone: walletClosedPositions === 0 ? 'bad' : velocityFillGrowth <= 0 || windowPnl < 0 || cohortProgress < 0.2 ? 'warn' : 'good',
        meta: `${formatNumber(walletClosedPositions)} closed / ${formatNumber(cohortResolved)}/${formatNumber(cohortTarget)} cohort`,
      },
    };

    const mode = MODES[state.guidanceMode] || MODES.repair;
    const stageTone = stageStatus[state.focusStage]?.tone || 'warn';
    const stageMeta = stageStatus[state.focusStage]?.meta || '';
    const loopHealthLabel = deriveLoopHealthLabel({
      serviceActive,
      launchBlocked,
      launchRepairRequired,
      verification,
      snapshotFreshness,
      velocityFillGrowth,
      btc5LiveRows,
      btc5LivePnl,
    });
    const watchpoints = buildWatchpoints({
      serviceActive,
      launchBlocked,
      launchRepairRequired,
      promotionHold,
      launchBlockerSummary,
      verification,
      snapshotFreshness,
      serviceFreshness,
      latestFillFreshness,
      forecastFreshness,
      btc5LiveRows,
      btc5LivePnl,
      velocityFillGrowth,
      velocityCycles,
      velocityWindowHours,
      tieOutConflict,
      tieOutStale,
      selectedDeployRecommendation,
      selectedPackageChecks,
    });
    const recommendations = buildRecommendations({
      mode: state.guidanceMode,
      focusStage: state.focusStage,
      launchBlocked,
      launchRepairRequired,
      promotionHold,
      blockedReasons,
      verification,
      btc5LivePnl,
      windowPnl,
      windowFills,
      windowHours,
      velocityFillGrowth,
      velocityCycles,
      serviceActive,
      snapshotFreshness,
      serviceFreshness,
      latestFillFreshness,
      tieOutConflict,
      tieOutStale,
      selectedDeployRecommendation,
      selectedPackageChecks,
    });
    const activeRecommendations = recommendations.filter(item => item.active).slice(0, 5);
    const highestPriority = activeRecommendations.length
      ? activeRecommendations
        .slice()
        .sort((left, right) => rankPriority(right.priority) - rankPriority(left.priority))[0].priority
      : 'clear';

    const systemPacketCount = Math.max(4, [
      frontierCandidates.length ? 1 : 0,
      policyBars.length ? 1 : 0,
      controlPlaneJobs.length ? 1 : 0,
      validationCohort.generated_at ? 1 : 0,
      healthSnapshot.generated_at ? 1 : 0,
      livePnl.generated_at ? 1 : 0,
      state.directives.length ? 1 : 0,
    ].reduce((sum, value) => sum + value, 0));
    const trendSummary = forecastTrendSeries.length
      ? `${forecastTrendSeries.length} checkpoints over ${formatHours(velocityWindowHours)}h. Active forecast moved from ${formatCompactPercent(forecastTrendSeries[0].active)} to ${formatCompactPercent(forecastTrendSeries[forecastTrendSeries.length - 1].active)} while validation fill growth stayed at +${formatNumber(velocityFillGrowth)}.`
      : 'No checked-in forecast trace published yet.';
    const lastAckAt = [
      pick(latestRuntimeControl, ['accepted_at'], null),
      pick(latestGuidance, ['accepted_at'], null),
    ].filter(Boolean).sort().slice(-1)[0] || null;
    const activeJobs = controlPlaneJobs.filter(job => job.enabled).length;
    const operatorApiStatus = artifacts.operatorApiBase
      ? `Hub API live at ${artifacts.operatorApiBase.replace(/^https?:\/\//, '')}${controlPlane.running ? ` · ${activeJobs} loop${activeJobs === 1 ? '' : 's'} armed` : ''}`
      : 'Hub API offline. Local queue only.';
    const lastAckLabel = lastAckAt
      ? `Last hub ack ${formatShortUtc(lastAckAt)}`
      : artifacts.operatorApiBase
        ? 'Hub API live. No accepted actions yet.'
        : 'No control ack yet.';
    const controls = {
      profile: pick(effectiveProfile, ['selected_profile', 'profile_name'], 'shadow_fast_flow'),
      yes_threshold: pick(effectiveProfile, ['signal_thresholds.yes_threshold'], ''),
      no_threshold: pick(effectiveProfile, ['signal_thresholds.no_threshold'], ''),
      max_resolution_hours: pick(effectiveProfile, ['market_filters.max_resolution_hours'], ''),
      hourly_notional_budget_usd: pick(effectiveProfile, ['risk_limits.hourly_notional_budget_usd'], ''),
      per_trade_cap_usd: pick(effectiveProfile, ['risk_limits.max_position_usd'], ''),
      enable_polymarket: Boolean(pick(effectiveProfile, ['feature_flags.enable_polymarket_venue'], false)),
      enable_kalshi: Boolean(pick(effectiveProfile, ['feature_flags.enable_kalshi_venue'], false)),
    };

    const overviewCards = [
      buildOverviewCard(
        stageStatus.evidence.tone,
        'Loop',
        loopHealthLabel,
        `${stageStatus.evidence.meta} · ${serviceActive ? 'runtime up' : 'runtime down'}`,
      ),
      buildOverviewCard(
        stageStatus.search.tone,
        'Autoresearch',
        String(currentDecision.action || autoresearch.decision?.action || 'hold').toUpperCase(),
        `${autoresearchFreshness.label} · ${formatNumber(recentProbe.validation_live_filled_rows || 0)} validated rows`,
      ),
      buildOverviewCard(
        stageStatus.execution.tone,
        'Live sleeve',
        formatUsd(btc5LivePnl),
        `${formatNumber(btc5LiveRows)} rows · last fill ${latestFillFreshness.label}`,
      ),
      buildOverviewCard(
        activeJobs >= 5 ? 'good' : activeJobs > 0 ? 'warn' : 'bad',
        'Training cadence',
        `${formatNumber(activeJobs)} jobs`,
        `${simulationLanes.length} lanes · ${formatNumber(velocityCycles)} cycles / ${formatHours(velocityWindowHours)}h`,
      ),
      buildOverviewCard(
        improvementResolvedPnl >= 0 ? 'good' : 'bad',
        'Improvement pulse',
        formatUsd(improvementResolvedPnl),
        `${formatNumber(improvementCandidateCount)} candidates · ${formatRatioPercent(improvementConversion)} conversion · ${formatUsd(improvementExecutedNotional)} hourly`,
      ),
      buildOverviewCard(
        championScore >= 90 ? 'good' : championScore > 0 ? 'warn' : 'neutral',
        'Champion edge',
        truncateText(championEdgeLabel, 28),
        `${championEvidenceBand} · ${championDeploymentClass} · score ${formatNumber(championScore, 1)}`,
      ),
    ];

    const frontierSummary = frontierCandidates.length
      ? `${frontierCandidates.length} runtime packages ranked. ${String(currentDecision.action || 'hold').toUpperCase()} · ${truncateText(String(currentDecision.reason || 'no decision reason published').replace(/;/g, ' · '), 64)}`
      : 'No ranked runtime packages published yet.';
    const simulationSummary = activeSimulationJobs.length
      ? `${activeSimulationJobs.length} live run${activeSimulationJobs.length === 1 ? '' : 's'} active: ${activeSimulationJobs.map(job => compactCandidateName(job)).join(', ')}. Champion edge: ${truncateText(championEdgeLabel, 52)}.`
      : simulationFindings.length
        ? `${simulationLanes.length} research lanes armed · latest finding from ${simulationFindings[0].lane || 'control plane'} · improvement ${stateImprovementFreshness.label}.`
        : `${simulationLanes.length} research lanes armed. Waiting for the first artifact-backed finding.`;
    const candidateSummary = championScore > 0
      ? `${truncateText(championEdgeLabel, 60)} is the current improvement champion (${championEvidenceBand}, score ${formatNumber(championScore, 1)}).`
      : frontierCandidates.length
        ? `${frontierCandidates[0].name} leads the published runtime packages by simulation profile.`
        : 'Candidate ledger waiting for autoresearch output.';
    const tradeTapeSummary = recentTradeRows.length
      ? `${formatNumber(normalizeNumber(tradingData.rows_total, recentTradeRows.length))} local trade rows · ${formatUsd(normalizeNumber(tradingData.realized_pnl_usd, 0))} realized · ${formatNumber(normalizeNumber(tradingData.pending_rows, 0))} pending · ${formatNumber(normalizeNumber(tradingData.skipped_rows, 0))} skips · latest ${latestFillFreshness.label}.`
      : 'No local trade tape rows published yet.';
    const policySummary = policyBars.length
      ? `${policyBars[0].name} beats the incumbent by ${formatUsd(policyBars[0].improvement, 0)} on the published loss frontier.`
      : 'Policy frontier not published.';
    const flowSummary = `${formatNumber(recentProbe.recent_window_rows || 0)} recent windows · skip rate ${formatRatioPercent(normalizeNumber(pick(autoresearch, ['execution_drag_summary.skip_rate'], 0), 0))} · order fail ${formatRatioPercent(normalizeNumber(recentProbe.recent_order_failed_rate, 0), 1)}.`;
    const cohortSummary = `${validationCohort.checkpoint_status || `${formatNumber(cohortResolved)}/${formatNumber(cohortTarget)} fills`} · rolling 24h ${formatUsd(rolling24hPnl)} · ET day ${formatUsd(normalizeNumber(etDay.net_after_rebate_pnl_usd, 0))}.`;

    const flowMetrics = [
      {
        label: 'Direction mix',
        tone: String(pick(recentProbe, ['recent_direction_mix.dominant_label'], '')).toUpperCase() === 'DOWN' ? 'good' : 'warn',
        bars: directionBuckets.map(bucket => ({
          label: bucket.label || bucket.name || bucket.direction || 'bucket',
          value: normalizeNumber(bucket.share, normalizeNumber(bucket.count, 0)),
          display: bucket.share !== undefined ? formatRatioPercent(bucket.share) : formatNumber(bucket.count || 0),
        })),
      },
      {
        label: 'Price buckets',
        tone: priceBuckets.length ? 'warn' : 'neutral',
        bars: priceBuckets.slice(0, 4).map(bucket => ({
          label: bucket.label || bucket.name || bucket.price_bucket || 'bucket',
          value: normalizeNumber(bucket.share, normalizeNumber(bucket.count, 0)),
          display: bucket.share !== undefined ? formatRatioPercent(bucket.share) : formatNumber(bucket.count || 0),
        })),
      },
      {
        label: 'Execution drag',
        tone: normalizeNumber(pick(autoresearch, ['execution_drag_summary.skip_rate'], 0), 0) > 0.3 ? 'bad' : 'warn',
        stats: [
          { label: 'skip rate', value: formatRatioPercent(normalizeNumber(pick(autoresearch, ['execution_drag_summary.skip_rate'], 0), 0)) },
          { label: 'failed', value: formatRatioPercent(normalizeNumber(pick(autoresearch, ['execution_drag_summary.order_failure_rate'], 0), 0)) },
          { label: 'sample', value: formatNumber(normalizeNumber(pick(autoresearch, ['execution_drag_summary.sample_size_rows'], 0), 0)) },
        ],
      },
      {
        label: 'Filter economics',
        tone: normalizeNumber(filterEconomics.total_filter_decisions, 0) > 0 ? 'warn' : 'neutral',
        stats: [
          { label: 'direction', value: formatUsd(normalizeNumber(pick(byFilter, ['direction_filter.total_counterfactual_usd'], 0), 0)) },
          { label: 'up shadow', value: formatUsd(normalizeNumber(pick(byFilter, ['up_live_mode.total_counterfactual_usd'], 0), 0)) },
          { label: 'cap', value: formatUsd(normalizeNumber(pick(byFilter, ['cap_breach.total_counterfactual_usd'], 0), 0)) },
        ],
      },
    ];

    const cohortPanel = {
      progress: clamp(cohortProgress, 0, 1),
      checkpointStatus: validationCohort.checkpoint_status || `${formatNumber(cohortResolved)}/${formatNumber(cohortTarget)} fills`,
      recommendation: validationCohort.recommendation || 'awaiting_data',
      tone: validationCohort.safety_kill_triggered ? 'bad' : cohortProgress >= 0.5 ? 'good' : 'warn',
      metrics: [
        { label: 'resolved fills', value: `${formatNumber(cohortResolved)}/${formatNumber(cohortTarget)}` },
        { label: 'net after rebate', value: formatUsd(normalizeNumber(validationCohort.net_pnl_after_estimated_rebate_usd, 0)) },
        { label: 'wins / losses', value: `${formatNumber(validationCohort.wins || 0)} / ${formatNumber(validationCohort.losses || 0)}` },
        { label: '24h', value: formatUsd(rolling24hPnl) },
        { label: 'ET day', value: formatUsd(normalizeNumber(etDay.net_after_rebate_pnl_usd, 0)) },
        { label: 'health flags', value: healthFlags.length ? healthFlags.join(', ') : 'none' },
      ],
    };

    const packet = {
      generated_at: new Date().toISOString(),
      packet_generated_at: new Date().toISOString(),
      source: 'manage-console',
      route: '/manage/',
      guidance_mode: state.guidanceMode,
      focus_stage: state.focusStage,
      runtime_posture: {
        loop_health: loopHealthLabel,
        launch_blocked: launchBlocked,
        launch_repair_required: launchRepairRequired,
        launch_blockers: blockedReasons,
        service_active: serviceActive,
        freshness: {
          snapshot: snapshotFreshness.label,
          service: serviceFreshness.label,
          latest_fill: latestFillFreshness.label,
          forecast: forecastFreshness.label,
        },
      },
      pnl_state: {
        sleeve_live_rows: btc5LiveRows,
        sleeve_live_pnl_usd: btc5LivePnl,
        window_fills: windowFills,
        window_pnl_usd: windowPnl,
      },
      learning_state: {
        wallet_closed_positions: walletClosedPositions,
        validation_fill_growth: velocityFillGrowth,
        cycles_in_window: velocityCycles,
        window_hours: velocityWindowHours,
      },
      directives: state.directives,
      recommendations: activeRecommendations.map(item => ({
        stage: item.stage,
        priority: item.priority,
        title: item.title,
        detail: item.detail,
      })),
      simulation_state: {
        autoresearch_generated_at: autoresearch.generated_at || null,
        active_jobs: activeSimulationJobs,
        lanes: simulationLanes,
        findings: simulationFindings.slice(0, 10),
        frontier_candidates: frontierCandidates.slice(0, 5).map(point => ({
          name: point.name,
          source: point.source,
          action: point.action,
          profit_probability: point.profitProbability,
          p95_max_drawdown_usd: point.drawdownUsd,
          median_total_pnl_usd: point.medianPnlUsd,
          validation_fill_count: point.fillCount,
        })),
      },
    };

    return {
      loopHealthLabel,
      focusStageLabel: `${STAGE_LABELS[state.focusStage]} Focus`,
      guidanceModeLabel: mode.label,
      freshnessShort: snapshotFreshness.tone === 'good' ? 'Fresh' : snapshotFreshness.tone === 'warn' ? 'Aging' : 'Stale',
      directiveCount: `${state.directives.length} directives`,
      systemPacketCount: `${systemPacketCount} feeds`,
      coreNote: `${mode.core} Current focus: ${STAGE_LABELS[state.focusStage]} (${stageMeta}).`,
      stageStatus,
      stageMeta: {
        search: stageStatus.search.meta,
        evidence: stageStatus.evidence.meta,
        gate: stageStatus.gate.meta,
        execution: stageStatus.execution.meta,
        learning: stageStatus.learning.meta,
      },
      trendSummary,
      trendStartLabel: forecastTrendSeries[0] ? formatShortUtc(forecastTrendSeries[0].timestamp) : 'no start',
      trendEndLabel: forecastTrendSeries[forecastTrendSeries.length - 1] ? formatShortUtc(forecastTrendSeries[forecastTrendSeries.length - 1].timestamp) : 'no end',
      trendSeries: forecastTrendSeries,
      recommendations: activeRecommendations,
      watchpoints,
      controls,
      overviewCards,
      simulationSummary,
      simulationLanes,
      simulationFindings,
      tradeTapeSummary,
      tradeTapeRows: recentTradeRows.slice(0, 12).map(row => ({
        slug: compactTradeSlug(row.slug),
        direction: row.direction || 'flat',
        status: row.order_status || 'unknown',
        tone: toneForTradeStatus(row.order_status),
        delta: Number(row.delta),
        orderPrice: Number(row.order_price),
        sizeUsd: Number(row.trade_size_usd),
        pnlUsd: Number(row.pnl_usd),
        activityAt: row.activity_at,
      })),
      frontierSummary,
      frontierCandidates,
      candidateSummary,
      policySummary,
      policyBars,
      flowSummary,
      flowMetrics,
      cohortSummary,
      cohortPanel,
      jobs: controlPlaneJobs,
      events: controlPlaneEvents.slice(-16).reverse(),
      canPushToApi: Boolean(artifacts.operatorApiBase),
      operatorApiStatus,
      lastAckLabel,
      packetPreview: JSON.stringify(packet, null, 2),
      packet,
      stageTone,
      priorityLabel: highestPriority,
      particleTones: buildParticleTones(systemPacketCount, stageStatus, state.focusStage),
    };
  }

  function deriveLoopHealthLabel(input) {
    let score = 100;
    if (!input.serviceActive) score -= 30;
    if (input.launchRepairRequired) score -= 24;
    else if (input.launchBlocked) score -= 8;
    if (input.verification.failed > 0) score -= 16;
    if (input.snapshotFreshness.tone === 'warn') score -= 10;
    if (input.snapshotFreshness.tone === 'bad') score -= 18;
    if (input.velocityFillGrowth <= 0) score -= 10;
    if (input.btc5LiveRows <= 0) score -= 12;
    if (input.btc5LivePnl < 0) score -= 8;
    if (score >= 76) return 'Working with evidence';
    if (score >= 46) return 'Degraded but observable';
    return 'Untrusted / cleanup first';
  }

  function rankPriority(value) {
    if (value === 'critical') return 4;
    if (value === 'high') return 3;
    if (value === 'medium') return 2;
    return 1;
  }

  function buildWatchpoints(input) {
    const watchpoints = [];
    watchpoints.push({
      tone: !input.serviceActive ? 'bad' : input.serviceFreshness.tone,
      title: 'Is it working?',
      detail: input.serviceActive
        ? `Runtime heartbeat is present, but service freshness is ${input.serviceFreshness.label}.`
        : 'Runtime heartbeat is absent. Treat all downstream surfaces as stale until the loop proves otherwise.',
    });
    watchpoints.push({
      tone: input.snapshotFreshness.tone,
      title: 'Are we getting updating data?',
      detail: `Snapshot is ${input.snapshotFreshness.label}; forecast is ${input.forecastFreshness.label}; latest fill is ${input.latestFillFreshness.label}.`,
    });
    watchpoints.push({
      tone: input.velocityFillGrowth > 0 ? 'good' : 'warn',
      title: 'Are the simulations running?',
      detail: `${formatNumber(input.velocityCycles)} cycles are published in the latest ${formatHours(input.velocityWindowHours)}h window, with validation fill growth at +${formatNumber(input.velocityFillGrowth)}.`,
    });
    watchpoints.push({
      tone: input.btc5LivePnl < 0 ? 'bad' : 'good',
      title: 'Why are we still losing money?',
      detail: `${formatUsd(input.btc5LivePnl)} live sleeve PnL across ${formatNumber(input.btc5LiveRows)} rows. If that remains negative, the console should bias toward bucket-level execution diagnosis before more tuning.`,
    });
    if (input.promotionHold) {
      watchpoints.push({
        tone: 'warn',
        title: 'Can we promote yet?',
        detail: `Not yet. Current deploy recommendation is ${input.selectedDeployRecommendation || 'hold'} with ${summarizeList(humanizeBlockedChecks(input.selectedPackageChecks), 2)} still gating promotion.`,
      });
    }
    if (input.launchRepairRequired || input.verification.failed > 0 || input.tieOutConflict || input.tieOutStale) {
      watchpoints.push({
        tone: 'bad',
        title: 'What needs cleanup first?',
        detail: [
          input.launchRepairRequired ? `launch blocked by ${input.launchBlockerSummary}` : null,
          input.verification.failed > 0 ? `${input.verification.failed} root test failures` : null,
          input.tieOutConflict ? 'wallet export conflict' : null,
          input.tieOutStale ? 'wallet export stale' : null,
        ].filter(Boolean).join('; '),
      });
    }
    return watchpoints;
  }

  function buildRecommendations(input) {
    const base = [
      {
        stage: 'gate',
        active: input.launchRepairRequired || input.promotionHold,
        tone: input.launchRepairRequired ? 'bad' : input.promotionHold ? 'warn' : 'good',
        priority: input.launchRepairRequired ? 'critical' : input.promotionHold ? 'high' : 'low',
        title: input.launchRepairRequired ? 'Repair launch truth before new tuning' : 'Respect the promotion hold',
        detail: input.launchRepairRequired
          ? `Launch is blocked by ${summarizeList(input.blockedReasons, 3)}. Repair the truth contract before trusting another optimization cycle.`
          : input.promotionHold
            ? `The runtime is intentionally staying in shadow. Latest package recommendation is ${input.selectedDeployRecommendation || 'hold'} with ${summarizeList(humanizeBlockedChecks(input.selectedPackageChecks), 2)} still gating promotion.`
            : 'Launch posture is aligned with the current evidence.',
        score: input.launchRepairRequired ? 90 : input.promotionHold ? 54 : 10,
      },
      {
        stage: 'evidence',
        active: input.snapshotFreshness.tone === 'bad'
          || input.serviceFreshness.tone === 'bad'
          || input.latestFillFreshness.tone === 'bad',
        tone: input.snapshotFreshness.tone === 'bad' || input.serviceFreshness.tone === 'bad'
          ? 'bad'
          : input.latestFillFreshness.tone === 'bad'
            ? 'warn'
            : 'good',
        priority: input.snapshotFreshness.tone === 'bad' || input.serviceFreshness.tone === 'bad'
          ? 'critical'
          : input.latestFillFreshness.tone === 'bad'
            ? 'medium'
            : 'low',
        title: input.snapshotFreshness.tone === 'bad' || input.serviceFreshness.tone === 'bad'
          ? 'Restore fresh status writers'
          : input.latestFillFreshness.tone === 'bad'
            ? 'Prove the runtime is still filling'
            : 'Keep evidence surfaces current',
        detail: input.snapshotFreshness.tone === 'bad' || input.serviceFreshness.tone === 'bad'
          ? `Snapshot ${input.snapshotFreshness.label}; service ${input.serviceFreshness.label}; latest fill ${input.latestFillFreshness.label}. If freshness drifts, the loop stops being legible.`
          : input.latestFillFreshness.tone === 'bad'
            ? `Status writers are current, but the latest fill is ${input.latestFillFreshness.label}. Treat this as execution dormancy or inactivity, not a telemetry success.`
            : `Snapshot ${input.snapshotFreshness.label}; service ${input.serviceFreshness.label}; latest fill ${input.latestFillFreshness.label}.`,
        score: input.snapshotFreshness.tone === 'bad' || input.serviceFreshness.tone === 'bad'
          ? 84
          : input.latestFillFreshness.tone === 'bad'
            ? 34
            : 12,
      },
      {
        stage: 'execution',
        active: input.btc5LivePnl < 0,
        tone: input.btc5LivePnl < 0 ? 'bad' : input.latestFillFreshness.tone === 'warn' ? 'warn' : 'good',
        priority: input.btc5LivePnl < 0 ? 'high' : 'medium',
        title: 'Diagnose the losing sleeve by fill behavior',
        detail: `${formatUsd(input.btc5LivePnl)} live PnL over ${formatNumber(input.windowFills)} recent fills and ${formatHours(input.windowHours)}h. Investigate direction, bucket, and fill cadence before scaling anything.`,
        score: input.btc5LivePnl < 0 ? 76 : 24,
      },
      {
        stage: 'learning',
        active: input.velocityFillGrowth <= 0,
        tone: input.velocityFillGrowth <= 0 ? 'warn' : 'good',
        priority: input.velocityFillGrowth <= 0 ? 'high' : 'medium',
        title: 'Force learning output, not just forecast churn',
        detail: `Validation fill growth is +${formatNumber(input.velocityFillGrowth)} across ${formatNumber(input.velocityCycles)} cycles. The loop should emit decision-grade evidence, not just more speculative traces.`,
        score: input.velocityFillGrowth <= 0 ? 72 : 24,
      },
      {
        stage: 'gate',
        active: input.verification.failed > 0,
        tone: input.verification.failed > 0 ? 'bad' : 'good',
        priority: input.verification.failed > 0 ? 'high' : 'low',
        title: 'Close regression debt',
        detail: input.verification.failed > 0
          ? `${input.verification.failed} root tests are failing. Clean this before treating new wins as trustworthy.`
          : 'Root verification is green enough that regressions are not the immediate blocker.',
        score: input.verification.failed > 0 ? 70 : 10,
      },
      {
        stage: 'search',
        active: false,
        tone: 'warn',
        priority: 'medium',
        title: 'Translate “make it better” into a ranked work order',
        detail: 'Tie each new hypothesis to a target stage, expected gain, and invalidation rule so the search side does not spray changes into an unclear control plane.',
        score: 40,
      },
    ];

    const modeWeights = (MODES[input.mode] || MODES.repair).stageWeights;
    return base
      .map(item => ({
        ...item,
        score: item.score + (modeWeights[item.stage] || 0) * 9 + (input.focusStage === item.stage ? 14 : 0),
      }))
      .sort((left, right) => right.score - left.score);
  }

  function buildParticleTones(count, stageStatus, focusStage) {
    const tones = [
      stageStatus[focusStage].tone,
      stageStatus.search.tone,
      stageStatus.evidence.tone,
      stageStatus.gate.tone,
      stageStatus.execution.tone,
      stageStatus.learning.tone,
    ];
    return Array.from({ length: count }, (_, index) => tones[index % tones.length]);
  }

  function renderConsole(data, state) {
    fillManageValues({
      directive_count: data.directiveCount,
      loop_health_label: data.loopHealthLabel,
      focus_stage_label: data.focusStageLabel,
      guidance_mode_label: data.guidanceModeLabel,
      freshness_short: data.freshnessShort,
      system_packet_count: data.systemPacketCount,
      operator_api_status: data.operatorApiStatus,
      last_ack_label: data.lastAckLabel,
      frontier_summary: data.frontierSummary,
      candidate_summary: data.candidateSummary,
      policy_summary: data.policySummary,
      flow_summary: data.flowSummary,
      cohort_summary: data.cohortSummary,
      trend_summary: data.trendSummary,
      trend_start_label: data.trendStartLabel,
      trend_end_label: data.trendEndLabel,
      priority_label: data.priorityLabel,
      simulation_summary: data.simulationSummary,
      trade_tape_summary: data.tradeTapeSummary,
    });

    renderDirectiveLog(state.directives);
    renderJobList(data.jobs);
    renderActionList(data.recommendations);
    renderEventFeed(data.events);
    renderWatchpoints(data.watchpoints);
    renderPacketPreview(data.packetPreview);
    renderOverviewCards(data.overviewCards);
    renderSimulationLanes(data.simulationLanes);
    renderSimulationFindings(data.simulationFindings);
    renderTradeTape(data.tradeTapeRows);
    renderFrontierChart(data.frontierCandidates);
    renderCandidateTable(data.frontierCandidates);
    renderPolicyChart(data.policyBars);
    renderFlowMetrics(data.flowMetrics);
    renderCohortPanel(data.cohortPanel);
    renderTrendChart(data.trendSeries);
    renderControlInputs(data.controls, data.canPushToApi);
    renderModeButtons(state.guidanceMode);
  }

  function applyPanelFocusFromUrl() {
    const panel = new URLSearchParams(window.location.search).get('panel');
    if (panel !== 'control-plane') return;
    const target = document.querySelector('[data-manage-events]')?.closest('.manage-panel-section')
      || document.querySelector('[data-manage-jobs]')?.closest('.manage-panel-section');
    if (!target) return;
    window.setTimeout(() => {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      target.classList.add('is-panel-focus');
      window.setTimeout(() => target.classList.remove('is-panel-focus'), 2200);
      showToast('Control-plane view loaded');
    }, 120);
  }

  function fillManageValues(values) {
    Object.entries(values).forEach(([key, value]) => {
      document.querySelectorAll(`[data-manage-fill="${key}"]`).forEach(element => {
        element.textContent = String(value);
      });
    });
  }

  function renderDirectiveLog(directives) {
    const host = document.querySelector('[data-manage-directive-log]');
    if (!host) return;
    if (!directives.length) {
      host.innerHTML = '<div class="manage-log-item"><div class="manage-log-title">No directives queued</div><div class="manage-log-detail">Use the command line or preset chips to set mode, focus a stage, and queue operator feedback.</div></div>';
      return;
    }
    host.innerHTML = directives.map(item => `
      <article class="manage-log-item">
        <div class="manage-log-topline">
          <div class="manage-log-title">${escapeHtml(item.text)}</div>
          <span class="manage-chip ${toneForMode(item.mode)}">${escapeHtml(titleCase(item.mode))}</span>
        </div>
        <div class="manage-log-meta">${escapeHtml(STAGE_LABELS[item.focusStage] || item.focusStage)} focus · ${escapeHtml(formatShortUtc(item.createdAt))}</div>
        <div class="manage-log-detail">${escapeHtml(item.note || 'Queued from the operator console.')}</div>
      </article>
    `).join('');
  }

  function renderControlInputs(controls, canPushToApi) {
    CONTROL_FIELDS.forEach(field => {
      const element = document.querySelector(`[data-manage-control="${field}"]`);
      if (!element) return;
      if (element instanceof HTMLInputElement && element.type === 'checkbox') {
        element.checked = Boolean(controls[field]);
      } else if (element instanceof HTMLInputElement) {
        element.value = controls[field] === null || controls[field] === undefined ? '' : String(controls[field]);
      }
    });

    document.querySelector('[data-manage-action="apply-controls"]')?.toggleAttribute('disabled', !canPushToApi);
    document.querySelector('[data-manage-action="push-guidance"]')?.toggleAttribute('disabled', !canPushToApi);
  }

  function renderJobList(items) {
    const host = document.querySelector('[data-manage-jobs]');
    if (!host) return;
    if (!items?.length) {
      host.innerHTML = '<div class="manage-log-item"><div class="manage-log-title">No loop jobs yet</div><div class="manage-log-detail">The local control plane has not published a scheduler snapshot.</div></div>';
      return;
    }
    host.innerHTML = items.map(item => {
      const tone = item.running ? 'good' : item.last_error ? 'bad' : item.enabled ? 'warn' : 'neutral';
      const lastRun = item.last_finished_at ? formatShortUtc(item.last_finished_at) : 'never';
      const nextRun = item.next_run_at ? formatShortUtc(item.next_run_at) : 'paused';
      return `
        <article class="manage-log-item">
          <div class="manage-log-topline">
            <div class="manage-log-title">${escapeHtml(item.label)}</div>
            <span class="manage-chip ${tone}">${escapeHtml(item.running ? 'running' : item.enabled ? 'armed' : 'paused')}</span>
          </div>
          <div class="manage-log-meta">last ${escapeHtml(lastRun)} · next ${escapeHtml(nextRun)}</div>
          <div class="manage-log-detail">${escapeHtml(jobSummary(item))}</div>
        </article>
      `;
    }).join('');
  }

  function renderEventFeed(items) {
    const host = document.querySelector('[data-manage-events]');
    if (!host) return;
    if (!items?.length) {
      host.innerHTML = '<article class="manage-watch-card warn"><div class="manage-watch-topline"><div class="manage-watch-title">Waiting for control-plane events</div><span class="manage-chip warn">Idle</span></div><div class="manage-watch-detail">When jobs start, complete, or fail, they will appear here.</div></article>';
      return;
    }
    host.innerHTML = items.map(item => {
      const tone = eventTone(item.type);
      const payload = item.payload || {};
      return `
        <article class="manage-watch-card ${tone}">
          <div class="manage-watch-topline">
            <div class="manage-watch-title">${escapeHtml(titleCase(String(item.type || '').replace(/\./g, ' ')))}</div>
            <span class="manage-chip ${tone}">${escapeHtml(formatShortUtc(item.ts))}</span>
          </div>
          <div class="manage-watch-detail">${escapeHtml(eventSummary(item.type, payload))}</div>
        </article>
      `;
    }).join('');
  }

  function renderActionList(items) {
    const host = document.querySelector('[data-manage-actions]');
    if (!host) return;
    if (!items.length) {
      host.innerHTML = `
        <article class="manage-action-card good">
          <div class="manage-action-topline">
            <div class="manage-action-title">No active blockers</div>
            <span class="manage-chip good">clear</span>
          </div>
          <div class="manage-log-meta">Control plane</div>
          <div class="manage-action-detail">The current checked-in state has no ranked blockers. Keep watching the live feed for drift.</div>
        </article>
      `;
      return;
    }
    host.innerHTML = items.map((item, index) => `
      <article class="manage-action-card ${item.tone}">
        <div class="manage-action-topline">
          <div class="manage-action-title">${index + 1}. ${escapeHtml(item.title)}</div>
          <span class="manage-chip ${item.tone}">${escapeHtml(item.priority)}</span>
        </div>
        <div class="manage-log-meta">${escapeHtml(STAGE_LABELS[item.stage])}</div>
        <div class="manage-action-detail">${escapeHtml(item.detail)}</div>
      </article>
    `).join('');
  }

  function renderWatchpoints(items) {
    const host = document.querySelector('[data-manage-watchpoints]');
    if (!host) return;
    host.innerHTML = items.map(item => `
      <article class="manage-watch-card ${item.tone}">
        <div class="manage-watch-topline">
          <div class="manage-watch-title">${escapeHtml(item.title)}</div>
          <span class="manage-chip ${item.tone}">${escapeHtml(titleCase(item.tone))}</span>
        </div>
        <div class="manage-watch-detail">${escapeHtml(item.detail)}</div>
      </article>
    `).join('');
  }

  function renderPacketPreview(text) {
    const host = document.querySelector('[data-manage-packet-preview]');
    if (!host) return;
    host.textContent = text;
  }

  function renderOverviewCards(items) {
    const host = document.querySelector('[data-manage-overview]');
    if (!host) return;
    host.innerHTML = (items || []).map(item => `
      <article class="manage-overview-card ${escapeHtml(item.tone)}">
        <div class="manage-overview-label">${escapeHtml(item.label)}</div>
        <div class="manage-overview-value">${escapeHtml(item.value)}</div>
        <div class="manage-overview-detail">${escapeHtml(item.detail)}</div>
      </article>
    `).join('');
  }

  function renderSimulationLanes(items) {
    const host = document.querySelector('[data-manage-simulation-lanes]');
    if (!host) return;
    if (!items?.length) {
      host.innerHTML = '<article class="manage-sim-lane warn"><div class="manage-sim-lane-topline"><div class="manage-sim-lane-title">No simulation lanes yet</div><span class="manage-chip warn">idle</span></div><div class="manage-sim-lane-detail">The local control plane has not published any research lanes.</div></article>';
      return;
    }
    host.innerHTML = items.map(item => `
      <article class="manage-sim-lane ${escapeHtml(item.tone)}">
        <div class="manage-sim-lane-topline">
          <div class="manage-sim-lane-title">${escapeHtml(item.label)}</div>
          <span class="manage-chip ${escapeHtml(item.tone)}">${escapeHtml(item.running ? 'running' : item.status || 'idle')}</span>
        </div>
        <div class="manage-log-meta">${escapeHtml(item.artifact || 'artifact unavailable')}</div>
        <div class="manage-sim-lane-headline">${escapeHtml(item.headline || 'No headline published')}</div>
        <div class="manage-sim-lane-detail">last ${escapeHtml(item.last_finished_at ? formatShortUtc(item.last_finished_at) : 'never')} · next ${escapeHtml(item.next_run_at ? formatShortUtc(item.next_run_at) : 'paused')}</div>
        <div class="manage-sim-mini-list">
          ${(item.findings || []).slice(0, 2).map(finding => `
            <div class="manage-sim-mini-item">
              <strong>${escapeHtml(finding.title || 'Finding')}</strong>
              <span>${escapeHtml(finding.detail || '')}</span>
            </div>
          `).join('')}
        </div>
      </article>
    `).join('');
  }

  function renderSimulationFindings(items) {
    const host = document.querySelector('[data-manage-simulation-findings]');
    if (!host) return;
    if (!items?.length) {
      host.innerHTML = '<article class="manage-watch-card warn"><div class="manage-watch-topline"><div class="manage-watch-title">Waiting for findings</div><span class="manage-chip warn">idle</span></div><div class="manage-watch-detail">Simulation findings will appear here as the research lanes publish artifacts.</div></article>';
      return;
    }
    host.innerHTML = items.slice(0, 10).map(item => `
      <article class="manage-watch-card ${escapeHtml(item.tone || 'warn')}">
        <div class="manage-watch-topline">
          <div class="manage-watch-title">${escapeHtml(item.title || 'Finding')}</div>
          <span class="manage-chip ${escapeHtml(item.tone || 'warn')}">${escapeHtml(item.lane || 'lane')}</span>
        </div>
        <div class="manage-log-meta">${escapeHtml(item.ts ? formatShortUtc(item.ts) : 'pending')}</div>
        <div class="manage-watch-detail">${escapeHtml(item.detail || '')}</div>
      </article>
    `).join('');
  }

  function renderTradeTape(rows) {
    const host = document.querySelector('[data-manage-trade-tape]');
    if (!host) return;
    if (!rows?.length) {
      host.innerHTML = '<div class="manage-subcopy">No local trading rows available yet.</div>';
      return;
    }
    host.innerHTML = `
      <div class="manage-rank-row manage-rank-row-head">
        <span>window</span>
        <span>dir</span>
        <span>status</span>
        <span>delta</span>
        <span>price</span>
      </div>
      ${rows.map(row => `
        <div class="manage-rank-row ${escapeHtml(row.tone)}">
          <span>${escapeHtml(row.slug)}</span>
          <span>${escapeHtml(row.direction)}</span>
          <span>${escapeHtml(row.status.replace(/_/g, ' '))}</span>
          <span>${Number.isFinite(row.delta) ? escapeHtml(formatNumber(row.delta, 4)) : 'n/a'}</span>
          <span>${Number.isFinite(row.orderPrice) ? escapeHtml(formatNumber(row.orderPrice, 2)) : 'n/a'}</span>
        </div>
      `).join('')}
    `;
  }

  function renderFrontierChart(points) {
    const host = document.querySelector('[data-manage-frontier-chart]');
    const legend = document.querySelector('[data-manage-frontier-legend]');
    if (!host || !legend) return;
    if (!points?.length) {
      host.innerHTML = '<div class="manage-subcopy">No published Monte Carlo frontier yet.</div>';
      legend.innerHTML = '';
      return;
    }

    const width = 720;
    const height = 360;
    const padding = { top: 28, right: 28, bottom: 42, left: 54 };
    const xValues = points.map(point => point.profitProbability * 100);
    const yValues = points.map(point => point.drawdownUsd);
    const fillValues = points.map(point => point.fillCount);
    const xMin = Math.min(0, ...xValues);
    const xMax = Math.max(100, ...xValues);
    const yMin = 0;
    const yMax = Math.max(1, ...yValues);
    const fillMax = Math.max(1, ...fillValues);
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    const x = value => padding.left + ((value - xMin) / Math.max(xMax - xMin, 1)) * innerWidth;
    const y = value => padding.top + ((value - yMin) / Math.max(yMax - yMin, 1)) * innerHeight;
    const radius = value => 8 + (Math.sqrt(Math.max(value, 0)) / Math.sqrt(fillMax || 1)) * 14;
    const toneColor = tone => {
      if (tone === 'good') return '#4ade80';
      if (tone === 'bad') return '#fb7185';
      return '#fbbf24';
    };
    const guideLines = Array.from({ length: 5 }, (_, index) => {
      const value = (index / 4) * yMax;
      return `<g><line x1="${padding.left}" y1="${y(value).toFixed(2)}" x2="${(width - padding.right).toFixed(2)}" y2="${y(value).toFixed(2)}" stroke="rgba(255,255,255,0.08)" stroke-width="1"></line><text x="${padding.left - 12}" y="${(y(value) + 4).toFixed(2)}" fill="rgba(179,192,214,0.72)" font-size="11" text-anchor="end">${escapeHtml(formatUsd(value, 0))}</text></g>`;
    }).join('');
    const xTicks = [0, 25, 50, 75, 100].map(value => `
      <g>
        <line x1="${x(value).toFixed(2)}" y1="${padding.top}" x2="${x(value).toFixed(2)}" y2="${(height - padding.bottom).toFixed(2)}" stroke="rgba(255,255,255,0.06)" stroke-width="1"></line>
        <text x="${x(value).toFixed(2)}" y="${height - 14}" fill="rgba(179,192,214,0.72)" font-size="11" text-anchor="middle">${escapeHtml(`${value}%`)}</text>
      </g>
    `).join('');
    const nodes = points.map(point => {
      const tone = frontierTone(point);
      const cx = x(point.profitProbability * 100);
      const cy = y(point.drawdownUsd);
      const r = radius(point.fillCount);
      const strokeWidth = point.isSelected ? 3 : 2;
      return `
        <g class="manage-frontier-node ${tone}">
          <circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="${r.toFixed(2)}" fill="${toneColor(tone)}" fill-opacity="${point.isSelected ? 0.26 : 0.18}" stroke="${toneColor(tone)}" stroke-width="${strokeWidth}"></circle>
          <circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="${Math.max(4, r * 0.22).toFixed(2)}" fill="${toneColor(tone)}"></circle>
          <text x="${cx.toFixed(2)}" y="${(cy - r - 10).toFixed(2)}" fill="#eef3ff" font-size="11" text-anchor="middle">${escapeHtml(point.name)}</text>
        </g>
      `;
    }).join('');

    host.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monte Carlo frontier">
        <rect x="0" y="0" width="${width}" height="${height}" rx="18" fill="rgba(255,255,255,0.02)"></rect>
        ${guideLines}
        ${xTicks}
        <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" stroke="rgba(255,255,255,0.12)" stroke-width="1.2"></line>
        <line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="rgba(255,255,255,0.12)" stroke-width="1.2"></line>
        ${nodes}
        <text x="${width / 2}" y="${height - 4}" fill="rgba(179,192,214,0.82)" font-size="12" text-anchor="middle">profit probability</text>
        <text x="14" y="${height / 2}" fill="rgba(179,192,214,0.82)" font-size="12" text-anchor="middle" transform="rotate(-90 14 ${height / 2})">p95 max drawdown</text>
      </svg>
    `;

    legend.innerHTML = points.map(point => `
      <div class="manage-frontier-legend-item ${escapeHtml(frontierTone(point))}">
        <span class="manage-frontier-legend-dot"></span>
        <span>${escapeHtml(point.name)}</span>
        <span>${escapeHtml(formatRatioPercent(point.profitProbability))}</span>
        <span>${escapeHtml(formatUsd(point.drawdownUsd, 0))}</span>
        <span>${escapeHtml(formatNumber(point.fillCount))} fills</span>
      </div>
    `).join('');
  }

  function renderCandidateTable(points) {
    const host = document.querySelector('[data-manage-candidate-table]');
    if (!host) return;
    if (!points?.length) {
      host.innerHTML = '<div class="manage-subcopy">No candidate ledger published yet.</div>';
      return;
    }
    host.innerHTML = `
      <div class="manage-rank-row manage-rank-row-head">
        <span>candidate</span>
        <span>action</span>
        <span>profit</span>
        <span>p95 dd</span>
        <span>fills</span>
      </div>
      ${points.map(point => `
        <div class="manage-rank-row ${escapeHtml(frontierTone(point))}">
          <span>${escapeHtml(point.name)}</span>
          <span>${escapeHtml(point.action || 'hold')}</span>
          <span>${escapeHtml(formatRatioPercent(point.profitProbability))}</span>
          <span>${escapeHtml(formatUsd(point.drawdownUsd, 0))}</span>
          <span>${escapeHtml(formatNumber(point.fillCount))}</span>
        </div>
      `).join('')}
    `;
  }

  function renderPolicyChart(items) {
    const host = document.querySelector('[data-manage-policy-chart]');
    if (!host) return;
    if (!items?.length) {
      host.innerHTML = '<div class="manage-subcopy">No policy frontier published yet.</div>';
      return;
    }
    const maxImprovement = Math.max(1, ...items.map(item => Math.abs(item.improvement)));
    host.innerHTML = items.map(item => `
      <div class="manage-policy-row">
        <div class="manage-policy-meta">
          <span class="manage-policy-name">${escapeHtml(item.name)}</span>
          <span class="manage-policy-value">${escapeHtml(formatUsd(item.improvement, 0))}</span>
        </div>
        <div class="manage-policy-bar">
          <span style="width:${((Math.abs(item.improvement) / maxImprovement) * 100).toFixed(1)}%"></span>
        </div>
        <div class="manage-policy-note">${escapeHtml(`${formatNumber(item.fillsPerDay, 1)} fills/day · CI ${formatUsd(item.confidenceLow, 0)} to ${formatUsd(item.confidenceHigh, 0)}`)}</div>
      </div>
    `).join('');
  }

  function renderFlowMetrics(items) {
    const host = document.querySelector('[data-manage-flow-metrics]');
    if (!host) return;
    if (!items?.length) {
      host.innerHTML = '<div class="manage-subcopy">No execution flow metrics published yet.</div>';
      return;
    }
    host.innerHTML = items.map(item => {
      const bars = Array.isArray(item.bars) ? item.bars.map(bar => {
        const width = clamp(bar.value <= 1 ? bar.value * 100 : bar.value, 0, 100);
        return `
          <div class="manage-flow-bar-row">
            <div class="manage-flow-bar-meta"><span>${escapeHtml(bar.label)}</span><span>${escapeHtml(bar.display)}</span></div>
            <div class="manage-flow-bar"><span style="width:${width.toFixed(1)}%"></span></div>
          </div>
        `;
      }).join('') : '';
      const stats = Array.isArray(item.stats) ? item.stats.map(stat => `
        <div class="manage-flow-stat">
          <span>${escapeHtml(stat.label)}</span>
          <strong>${escapeHtml(stat.value)}</strong>
        </div>
      `).join('') : '';
      return `
        <article class="manage-flow-card ${escapeHtml(item.tone)}">
          <div class="manage-flow-title">${escapeHtml(item.label)}</div>
          ${bars || `<div class="manage-flow-stats">${stats}</div>`}
        </article>
      `;
    }).join('');
  }

  function renderCohortPanel(panel) {
    const host = document.querySelector('[data-manage-cohort-panel]');
    if (!host) return;
    if (!panel) {
      host.innerHTML = '<div class="manage-subcopy">No cohort panel available.</div>';
      return;
    }
    host.innerHTML = `
      <div class="manage-cohort-progress ${escapeHtml(panel.tone)}">
        <div class="manage-cohort-progress-topline">
          <span>${escapeHtml(panel.checkpointStatus)}</span>
          <span>${escapeHtml(panel.recommendation)}</span>
        </div>
        <div class="manage-cohort-progress-bar"><span style="width:${(panel.progress * 100).toFixed(1)}%"></span></div>
      </div>
      <div class="manage-cohort-metrics">
        ${panel.metrics.map(metric => `
          <div class="manage-cohort-metric">
            <span>${escapeHtml(metric.label)}</span>
            <strong>${escapeHtml(metric.value)}</strong>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderTrendChart(series) {
    const host = document.querySelector('[data-manage-trend-chart]');
    if (!host) return;
    if (!series.length) {
      host.innerHTML = '<div class="manage-subcopy">No checked-in forecast trend published yet.</div>';
      return;
    }

    const width = 620;
    const height = 240;
    const padding = 22;
    const values = series.flatMap(point => [point.active, point.best]);
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const span = Math.max(maxValue - minValue, 1);
    const xStep = series.length > 1 ? (width - padding * 2) / (series.length - 1) : 0;
    const x = index => padding + xStep * index;
    const y = value => height - padding - (((value - minValue) / span) * (height - padding * 2));
    const pathFor = key => series.map((point, index) => `${index === 0 ? 'M' : 'L'} ${x(index).toFixed(2)} ${y(point[key]).toFixed(2)}`).join(' ');
    const maxFills = Math.max(1, ...series.map(point => point.fills));
    const bars = series.map((point, index) => {
      const barHeight = (point.fills / maxFills) * 44;
      return `<rect x="${(x(index) - 10).toFixed(2)}" y="${(height - padding - barHeight).toFixed(2)}" width="20" height="${barHeight.toFixed(2)}" rx="6"></rect>`;
    }).join('');
    const points = series.map((point, index) => `<circle cx="${x(index).toFixed(2)}" cy="${y(point.active).toFixed(2)}" r="4"></circle>`).join('');

    host.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Manage trend chart">
        <defs>
          <linearGradient id="manageTrendActive" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#4da3ff"></stop>
            <stop offset="100%" stop-color="#7ce7ff"></stop>
          </linearGradient>
          <linearGradient id="manageTrendBest" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#9b8cff"></stop>
            <stop offset="100%" stop-color="#fbbf24"></stop>
          </linearGradient>
        </defs>
        <g>
          <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="rgba(255,255,255,0.12)" stroke-width="1"></line>
          <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="rgba(255,255,255,0.12)" stroke-width="1"></line>
        </g>
        <g fill="rgba(255,255,255,0.11)">${bars}</g>
        <path d="${pathFor('best')}" fill="none" stroke="url(#manageTrendBest)" stroke-width="4" stroke-dasharray="8 8" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="${pathFor('active')}" fill="none" stroke="url(#manageTrendActive)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
        <g fill="#eef3ff" stroke="#4da3ff" stroke-width="2">${points}</g>
      </svg>
    `;
  }

  function renderParticles(tones) {
    const host = document.querySelector('[data-manage-particle-field]');
    if (!host) return;
    host.innerHTML = '';
    tones.forEach((tone, index) => {
      const particle = document.createElement('div');
      particle.className = `manage-particle is-${tone}`;
      particle.style.setProperty('--duration', `${12 + (index % 4) * 2}s`);
      particle.style.setProperty('--delay', `${(index * -1.1).toFixed(1)}s`);
      particle.style.setProperty('--start', `${index * (360 / tones.length)}deg`);
      particle.style.setProperty('--size', `${10 + (index % 3) * 2}px`);
      particle.innerHTML = '<span class="manage-particle-dot"></span>';
      host.appendChild(particle);
    });
  }

  function renderStageState(stageStatus, focusStage) {
    STAGES.forEach(stage => {
      const node = document.querySelector(`[data-manage-stage-node="${stage}"]`);
      if (!node) return;
      node.classList.remove('is-good', 'is-warn', 'is-bad', 'is-focused');
      node.classList.add(`is-${stageStatus[stage].tone}`);
      if (stage === focusStage) {
        node.classList.add('is-focused');
      }
    });
  }

  function renderModeButtons(activeMode) {
    document.querySelectorAll('[data-manage-mode]').forEach(button => {
      button.classList.toggle('is-active', button.getAttribute('data-manage-mode') === activeMode);
    });
  }

  function positionFocusBeam(focusStage) {
    const beam = document.querySelector('[data-manage-focus-beam]');
    const theater = document.querySelector('.manage-theater');
    const node = document.querySelector(`[data-manage-stage-node="${focusStage}"]`);
    if (!beam || !theater || !node) return;
    const theaterRect = theater.getBoundingClientRect();
    const nodeRect = node.getBoundingClientRect();
    const centerX = theaterRect.width / 2;
    const centerY = theaterRect.height / 2;
    const nodeX = (nodeRect.left - theaterRect.left) + nodeRect.width / 2;
    const nodeY = (nodeRect.top - theaterRect.top) + nodeRect.height / 2;
    const dx = nodeX - centerX;
    const dy = nodeY - centerY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    const angle = Math.atan2(dy, dx) * (180 / Math.PI) + 90;
    beam.style.height = `${Math.max(distance - 60, 40)}px`;
    beam.style.left = `${centerX - 2}px`;
    beam.style.top = `${centerY}px`;
    beam.style.transform = `rotate(${angle}deg)`;
  }

  function parseNumberField(value) {
    if (value === '' || value === null || value === undefined) return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function readControlPayload() {
    if (!runtimeData) return null;
    const current = runtimeData.controls || {};
    const payload = {};

    const profileInput = document.querySelector('[data-manage-control="profile"]');
    if (profileInput instanceof HTMLInputElement) {
      const value = profileInput.value.trim() || current.profile || 'shadow_fast_flow';
      if (value !== current.profile) payload.profile = value;
    }

    ['yes_threshold', 'no_threshold', 'max_resolution_hours', 'hourly_notional_budget_usd', 'per_trade_cap_usd'].forEach(field => {
      const element = document.querySelector(`[data-manage-control="${field}"]`);
      if (!(element instanceof HTMLInputElement)) return;
      const nextValue = parseNumberField(element.value);
      const currentValue = parseNumberField(current[field]);
      if (nextValue !== currentValue) {
        payload[field] = nextValue;
      }
    });

    ['enable_polymarket', 'enable_kalshi'].forEach(field => {
      const element = document.querySelector(`[data-manage-control="${field}"]`);
      if (!(element instanceof HTMLInputElement)) return;
      if (Boolean(element.checked) !== Boolean(current[field])) {
        payload[field] = Boolean(element.checked);
      }
    });

    if (!Object.keys(payload).length) {
      return null;
    }

    payload.guidance_mode = consoleState.guidanceMode;
    payload.focus_stage = consoleState.focusStage;
    payload.reason = consoleState.directives[0]?.text || 'Applied from /manage/ runtime levers';
    return payload;
  }

  function buildGuidanceRequest() {
    if (!runtimeData) return null;
    return {
      route: runtimeData.packet.route,
      source: 'manage-console',
      packet_generated_at: runtimeData.packet.packet_generated_at || runtimeData.packet.generated_at,
      guidance_mode: runtimeData.packet.guidance_mode,
      focus_stage: runtimeData.packet.focus_stage,
      runtime_posture: runtimeData.packet.runtime_posture,
      pnl_state: runtimeData.packet.pnl_state,
      learning_state: runtimeData.packet.learning_state,
      recommendations: runtimeData.packet.recommendations,
      directives: consoleState.directives.map(item => ({
        id: item.id,
        text: item.text,
        note: item.note,
        mode: item.mode,
        focus_stage: item.focusStage,
        created_at: item.createdAt,
      })),
    };
  }

  async function submitGuidancePacket() {
    const payload = buildGuidanceRequest();
    if (!payload) return;
    await postOperatorJson('/api/v1/operator/guidance', payload);
    await refreshConsole();
    showToast('Guidance packet pushed to hub');
  }

  async function applyRuntimeControls() {
    const payload = readControlPayload();
    if (!payload) {
      showToast('No lever changes detected');
      return;
    }
    await postOperatorJson('/api/v1/operator/runtime-controls', payload);
    await refreshConsole();
    showToast('Runtime controls acknowledged');
  }

  async function runControlPlaneJob(jobName) {
    await postOperatorJson(`/api/v1/control-plane/jobs/${jobName}/run`, {});
    await refreshConsole();
    showToast(`${titleCase(jobName)} job started`);
  }

  function bindStaticEvents() {
    const commandInput = document.getElementById('manage-command-input');
    document.querySelector('[data-manage-action="execute-command"]')?.addEventListener('click', () => {
      executeCurrentCommand();
    });

    commandInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        executeCurrentCommand();
      }
    });

    document.querySelectorAll('[data-manage-mode]').forEach(button => {
      button.addEventListener('click', async () => {
        consoleState.guidanceMode = button.getAttribute('data-manage-mode') || 'repair';
        saveConsoleState();
        await refreshConsole();
        showToast(`Mode set to ${MODES[consoleState.guidanceMode].label}`);
      });
    });

    document.querySelectorAll('[data-manage-stage-node]').forEach(node => {
      node.addEventListener('click', async () => {
        const focusStage = node.getAttribute('data-manage-stage-node');
        if (!STAGES.includes(focusStage)) return;
        consoleState.focusStage = focusStage;
        saveConsoleState();
        await refreshConsole();
        showToast(`${STAGE_LABELS[focusStage]} focus selected`);
      });
    });

    document.querySelector('[data-manage-action="clear-directives"]')?.addEventListener('click', async () => {
      consoleState.directives = [];
      saveConsoleState();
      await refreshConsole();
      showToast('Directive queue cleared');
    });

    document.querySelector('[data-manage-action="copy-packet"]')?.addEventListener('click', async () => {
      if (!runtimeData) return;
      const text = JSON.stringify(runtimeData.packet, null, 2);
      try {
        await navigator.clipboard.writeText(text);
        showToast('Feedback packet copied');
      } catch (_error) {
        showToast('Clipboard write failed');
      }
    });

    document.querySelector('[data-manage-action="download-packet"]')?.addEventListener('click', () => {
      if (!runtimeData) return;
      const blob = new Blob([JSON.stringify(runtimeData.packet, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `elastifund-manage-packet-${Date.now()}.json`;
      link.click();
      URL.revokeObjectURL(url);
      showToast('Feedback packet downloaded');
    });

    document.querySelector('[data-manage-action="apply-controls"]')?.addEventListener('click', async () => {
      try {
        await applyRuntimeControls();
      } catch (error) {
        showToast(error.message || 'Runtime control apply failed');
      }
    });

    document.querySelector('[data-manage-action="push-guidance"]')?.addEventListener('click', async () => {
      try {
        await submitGuidancePacket();
      } catch (error) {
        showToast(error.message || 'Guidance push failed');
      }
    });

    document.querySelectorAll('[data-manage-run-job]').forEach(button => {
      button.addEventListener('click', async () => {
        const jobName = button.getAttribute('data-manage-run-job');
        if (!jobName) return;
        try {
          await runControlPlaneJob(jobName);
        } catch (error) {
          showToast(error.message || `${jobName} run failed`);
        }
      });
    });

    window.addEventListener('resize', () => {
      positionFocusBeam(consoleState.focusStage);
    });
  }

  async function executeCurrentCommand() {
    const input = document.getElementById('manage-command-input');
    if (!(input instanceof HTMLInputElement)) return;
    const text = input.value.trim();
    if (!text) return;
    const result = applyCommand(text);
    input.value = '';
    saveConsoleState();
    await refreshConsole();
    showToast(result);
  }

  function applyCommand(text) {
    const command = text.trim();
    if (!command.startsWith('/')) {
      queueDirective(command, '');
      return 'Directive queued';
    }

    const [, verb = '', ...rest] = command.split(/\s+/);
    const arg = rest.join(' ').trim();

    if (verb === 'mode' && MODES[arg]) {
      consoleState.guidanceMode = arg;
      return `Mode set to ${MODES[arg].label}`;
    }

    if (verb === 'focus' && STAGES.includes(arg)) {
      consoleState.focusStage = arg;
      return `Focus moved to ${STAGE_LABELS[arg]}`;
    }

    if (verb === 'queue' && arg) {
      queueDirective(arg, 'Queued from slash command');
      return 'Directive queued';
    }

    if (verb === 'clear') {
      consoleState.directives = [];
      return 'Directive queue cleared';
    }

    return 'Unknown command';
  }

  function queueDirective(text, note) {
    consoleState.directives = [
      {
        id: `directive-${Date.now()}`,
        text,
        note: note || 'Queued from operator console',
        mode: consoleState.guidanceMode,
        focusStage: consoleState.focusStage,
        createdAt: new Date().toISOString(),
      },
      ...consoleState.directives,
    ].slice(0, 16);
  }

  function toneForMode(mode) {
    if (mode === 'exploit') return 'good';
    if (mode === 'repair' || mode === 'gate') return 'bad';
    return 'warn';
  }

  function eventTone(type) {
    if (String(type).includes('failed')) return 'bad';
    if (String(type).includes('completed') || String(type).includes('started')) return 'good';
    return 'warn';
  }

  function jobSummary(item) {
    const summary = item.last_output_summary || {};
    const bits = [
      summary.action ? `action ${summary.action}` : null,
      summary.recommendation ? `recommendation ${summary.recommendation}` : null,
      summary.checkpoint_status ? summary.checkpoint_status : null,
      summary.net_value_usd !== undefined && summary.net_value_usd !== null ? `net ${formatUsd(summary.net_value_usd)}` : null,
      summary.rolling_win_rate_50 !== undefined && summary.rolling_win_rate_50 !== null ? `win rate ${formatNumber(summary.rolling_win_rate_50 * 100, 1)}%` : null,
      summary.resolved_down_fills !== undefined && summary.resolved_down_fills !== null ? `${formatNumber(summary.resolved_down_fills)} fills` : null,
      summary.best_candidate ? `best ${summary.best_candidate}` : null,
      summary.best_hypothesis ? `hypothesis ${summary.best_hypothesis}` : null,
      summary.policy_id ? `policy ${summary.policy_id}` : null,
      summary.leader ? `leader ${summary.leader}` : null,
      item.last_error ? `error ${item.last_error}` : null,
    ].filter(Boolean);
    return bits.length ? bits.join(' · ') : 'No completed run yet.';
  }

  function eventSummary(type, payload) {
    if (type === 'job.started') {
      return `${titleCase(payload.label || payload.job)} started from ${payload.source || 'scheduler'}.`;
    }
    if (type === 'job.completed') {
      const summary = payload.summary || {};
      return [
        `${titleCase(payload.label || payload.job)} completed.`,
        summary.action ? `action ${summary.action}` : null,
        summary.recommendation ? `recommendation ${summary.recommendation}` : null,
        summary.best_candidate ? `best ${summary.best_candidate}` : null,
      ].filter(Boolean).join(' ');
    }
    if (type === 'job.failed') {
      return `${titleCase(payload.label || payload.job)} failed: ${payload.error || 'unknown error'}`;
    }
    if (type === 'simulation.findings') {
      const lane = payload.lane || {};
      return `${lane.label || payload.label || payload.job}: ${lane.headline || 'new findings published'}.`;
    }
    if (type === 'control_plane.started') {
      return 'Local scheduler started. Heartbeat jobs are armed.';
    }
    if (type === 'job.paused' || type === 'job.resumed') {
      return `${titleCase(payload.job)} ${type.endsWith('paused') ? 'paused' : 'resumed'}.`;
    }
    return JSON.stringify(payload);
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showToast(message) {
    const existing = document.querySelector('.manage-toast');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.className = 'manage-toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    window.setTimeout(() => {
      toast.remove();
    }, 2200);
  }
})();
