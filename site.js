const DEFAULTS = {
  cycleLabel: 'Flywheel Cycle 2',
  cycleNumber: 2,
  calibratedWinRate: '71.2%',
  legacyWinRate: '68.5%',
  noOnlyWinRate: '76.2%',
  strategyCatalog: {
    total: 131,
    deployed: 7,
    building: 8,
    rejected: 18,
    pipeline: 97,
    reevaluating: 1
  },
  dispatchWorkOrders: 11,
  researchFiles: 95,
  benchmarkedSystems: 23,
  primarySignalLanes: 6,
  anomalySignalLanes: 1,
  commitCount: 37,
  diaryEntries: 14,
  risk: {
    positionUsd: '$5',
    dailyLossUsd: '$5',
    kelly: '0.25',
    maxOpenPositions: 5
  },
  server: {
    location: 'Dublin VPS',
    detail: 'AWS Lightsail eu-west-1'
  },
  nextMilestone: 'First live trade',
  deployBlocker: 'release manifest validation remains blocked while runtime bundle artifacts are reconciled'
};

const PUBLIC_SITE_SNAPSHOT = {
  trackedCapitalUsd: 347.51,
  deployedCapitalUsd: 0,
  cyclesCompleted: 311,
  totalTrades: 0,
  closedTrades: 0,
  verifiedTestsTotal: 1278,
  strategyTotal: 131,
  primarySignalLanes: 6,
  anomalySignalLanes: 1,
  walletCount: 80,
  walletReady: true,
  walletStatus: 'ready',
  fastVerdict: 'REJECT ALL'
};

function getPathValue(source, path) {
  return path.split('.').reduce((current, key) => {
    if (current && Object.prototype.hasOwnProperty.call(current, key)) {
      return current[key];
    }
    return undefined;
  }, source);
}

function pick(source, paths, fallback = undefined) {
  if (!source) return fallback;
  for (const path of paths) {
    const value = getPathValue(source, path);
    if (value !== undefined && value !== null) {
      return value;
    }
  }
  return fallback;
}

function rootPath(path) {
  if (!path) return null;
  return path.startsWith('/') ? path : `/${path.replace(/^\.?\//, '')}`;
}

async function fetchJson(path) {
  if (!path) return null;
  try {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    return null;
  }
}

async function fetchText(path) {
  if (!path) return null;
  try {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) return null;
    return await response.text();
  } catch (error) {
    return null;
  }
}

function formatUsd(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(Number(value || 0));
}

function formatLongDate(value) {
  if (!value) return 'March 9, 2026';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'March 9, 2026';
  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC'
  }).format(date);
}

function formatUtc(value) {
  if (!value) return '2026-03-09 00:48 UTC';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '2026-03-09 00:48 UTC';
  return date.toISOString().replace('T', ' ').replace(/\.\d+Z$/, ' UTC');
}

function titleCase(value) {
  return String(value || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, letter => letter.toUpperCase());
}

function normalizeNumber(value, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function humanizeBlockedChecks(checks) {
  const labels = {
    service_not_running: 'service not running',
    no_closed_trades: 'no closed trades',
    no_deployed_capital: 'no deployed capital',
    a6_gate_blocked: 'A-6 blocked',
    b1_gate_blocked: 'B-1 blocked',
    flywheel_not_green: 'flywheel hold',
    root_tests_not_passing: 'verification not green'
  };
  return (checks || []).map(item => labels[item] || item.replace(/_/g, ' '));
}

function parseVerificationSummary(summary) {
  const failedMatch = /(\d+)\s+failed/.exec(summary || '');
  const passedMatches = Array.from((summary || '').matchAll(/(\d+)\s+passed/g));
  return {
    failed: failedMatch ? Number(failedMatch[1]) : 0,
    passedTotal: passedMatches.length
      ? passedMatches.reduce((sum, match) => sum + Number(match[1]), 0)
      : 0
  };
}

function buildVerificationSummary(rootTestStatus, snapshot) {
  const rootStatus = String(pick(rootTestStatus, ['status'], '')).toLowerCase();
  const rootSummary = pick(rootTestStatus, ['summary'], null);
  if (rootStatus === 'failing') {
    const outputTail = Array.isArray(rootTestStatus?.output_tail) ? rootTestStatus.output_tail : [];
    const errorLine = outputTail.find(line => /ImportError|ModuleNotFoundError|FAILED|Error \d+/i.test(line));
    return errorLine ? `make test failing (${errorLine.trim()})` : (rootSummary || 'make test failing');
  }
  return rootSummary || pick(snapshot, ['verification.summary'], 'verification status unavailable');
}

function parseRiskRails(text) {
  const match = (text || '').match(
    /Live config[^.\n]*?\$([0-9.]+)\/position,\s*([0-9]+)\s*max open positions,\s*\$([0-9.]+)\s*daily loss cap,\s*([0-9.]+)\s*Kelly,\s*([0-9]+)h max resolution/i
  );
  if (!match) {
    return { ...DEFAULTS.risk };
  }
  return {
    positionUsd: `$${match[1]}`,
    maxOpenPositions: Number(match[2]),
    dailyLossUsd: `$${match[3]}`,
    kelly: match[4]
  };
}

function parsePerformanceMetrics(text) {
  const calibratedMatch = (text || '').match(/Current calibrated selective benchmark\s*\|[^\n|]*\|\s*([0-9.]+%)/i);
  const legacyMatch = (text || '').match(/Legacy calibrated reference\s*\|[^\n|]*\|\s*([0-9.]+%)/i);
  return {
    calibrated: calibratedMatch?.[1] || DEFAULTS.calibratedWinRate,
    legacy: legacyMatch?.[1] || DEFAULTS.legacyWinRate
  };
}

function parseSignalLaneMetrics(text) {
  const match = (text || '').match(/`(\d+)` primary \+ `(\d+)` anomaly signal lane/i);
  return {
    primary: match ? Number(match[1]) : DEFAULTS.primarySignalLanes,
    anomaly: match ? Number(match[2]) : DEFAULTS.anomalySignalLanes
  };
}

function buildResolutionDistribution(markets) {
  const buckets = [
    { key: '<1h', count: 0 },
    { key: '1-4h', count: 0 },
    { key: '4-24h', count: 0 },
    { key: '>24h', count: 0 }
  ];

  for (const market of markets) {
    const hours = Number(market?.resolution_hours);
    if (!Number.isFinite(hours)) continue;
    if (hours < 1) {
      buckets[0].count += 1;
    } else if (hours <= 4) {
      buckets[1].count += 1;
    } else if (hours <= 24) {
      buckets[2].count += 1;
    } else {
      buckets[3].count += 1;
    }
  }

  const summary = buckets
    .filter(bucket => bucket.count > 0)
    .map(bucket => `${bucket.count} ${bucket.key}`)
    .join(' / ');

  return summary || 'no current public-safe opportunity windows';
}

function summarizeEdgeScan(edgeScan) {
  const confirmed = Array.isArray(edgeScan?.candidate_markets) ? edgeScan.candidate_markets : [];
  const transient = Array.isArray(edgeScan?.recent_transient_candidates) ? edgeScan.recent_transient_candidates : [];
  const publicMarkets = [...confirmed, ...transient];
  const directCategories = Array.from(new Set(
    publicMarkets.flatMap(market => {
      if (Array.isArray(market?.signal_sources)) return market.signal_sources;
      if (market?.source) return [market.source];
      if (market?.family) return [market.family];
      return [];
    })
  ));
  const fallbackCategories = [];
  if (normalizeNumber(edgeScan?.lane_health?.wallet_flow?.signals_found, 0) > 0) {
    fallbackCategories.push('Wallet Flow');
  }
  if (normalizeNumber(edgeScan?.lane_health?.vpin?.tokens_tracked, 0) > 0) {
    fallbackCategories.push('VPIN/OFI Toxicity');
  }
  if (normalizeNumber(edgeScan?.lane_health?.a6?.candidates, 0) > 0) {
    fallbackCategories.push('A-6');
  }
  if (normalizeNumber(edgeScan?.lane_health?.cross_platform_arb?.opportunities_found, 0) > 0) {
    fallbackCategories.push('Cross Platform Arb');
  }
  if (normalizeNumber(edgeScan?.lane_health?.lmsr?.signals_found, 0) > 0) {
    fallbackCategories.push('LMSR');
  }
  const categories = directCategories.length ? directCategories : fallbackCategories;
  const publicCount = publicMarkets.length;

  return {
    summary: publicCount === 0
      ? '0 opportunities found'
      : confirmed.length > 0
        ? `${confirmed.length} confirmed opportunities, ${transient.length} transient observations`
        : `0 confirmed opportunities, ${transient.length} transient observations`,
    countLabel: publicCount === 0 ? '0 opportunities found' : `${publicCount} public-safe observations`,
    categories: categories.length ? categories.map(value => titleCase(value)).join(', ') : 'no public categories',
    resolutionDistribution: buildResolutionDistribution(publicMarkets)
  };
}

function setAll(attribute, key, value) {
  document.querySelectorAll(`[${attribute}="${key}"]`).forEach(element => {
    element.textContent = value;
  });
}

function setCommonValues(data) {
  const values = {
    cycle_label: data.cycleLabel,
    sprint_cycle: `Cycle ${data.cycleNumber}`,
    tracked_capital: formatUsd(data.capitalTracked),
    undeployed_capital: formatUsd(data.capitalTracked - data.capitalDeployed),
    deployed_capital: formatUsd(data.capitalDeployed),
    polymarket_capital: formatUsd(data.polymarketCapital),
    kalshi_capital: formatUsd(data.kalshiCapital),
    runtime_cycles: String(data.cyclesCompleted),
    live_trades: String(data.totalTrades),
    live_closed_trades: String(data.closedTrades),
    wallet_count: String(data.walletCount),
    wallet_status: data.walletReady ? 'ready' : data.walletStatus,
    strategy_total: String(data.strategyCatalog.total),
    strategy_distribution: `${data.strategyCatalog.deployed} deployed / ${data.strategyCatalog.building} building / ${data.strategyCatalog.rejected} rejected / ${data.strategyCatalog.pipeline} pipeline${data.strategyCatalog.reevaluating ? ` (+${data.strategyCatalog.reevaluating} re-evaluating)` : ''}`,
    dispatch_orders: String(data.dispatchWorkOrders),
    dispatch_work_orders: String(data.dispatchWorkOrders),
    dispatch_archive: String(data.researchFiles),
    research_files: String(data.researchFiles),
    benchmarked_systems: String(data.benchmarkedSystems),
    signal_lane_total: String(data.primarySignalLanes + data.anomalySignalLanes),
    signal_lanes: `${data.primarySignalLanes + data.anomalySignalLanes} total (${data.primarySignalLanes} primary + ${data.anomalySignalLanes} anomaly)`,
    calibrated_win_rate: data.calibratedWinRate,
    legacy_win_rate: data.legacyWinRate,
    no_only_win_rate: data.noOnlyWinRate || DEFAULTS.noOnlyWinRate,
    verification_summary: data.verificationSummary,
    verification_current: `${data.verificationBaselineTotal.toLocaleString('en-US')} verified`,
    verification_baseline: `${data.verificationBaselineTotal.toLocaleString('en-US')} total verified in the March 9 snapshot`,
    verification_root: data.verificationRootDetail,
    service_state: data.serviceStateLabel,
    service_surface: data.serviceSurface,
    service_checked_at: formatUtc(data.serviceCheckedAt),
    service_checked_date: formatLongDate(data.serviceCheckedAt),
    service_drift_note: data.serviceDriftNote,
    server_location: data.serverLocation,
    server_detail: data.serverDetail,
    launch_posture: data.launchBlocked ? 'launch blocked' : 'launch clear',
    launch_reasons: data.launchReasons.join(', '),
    next_action: data.nextAction,
    fast_verdict: data.fastVerdict,
    fast_markets: String(data.fastMarketsObserved),
    fast_breakdown: `${data.fastMarkets15m} 15m / ${data.fastMarkets5m} 5m / ${data.fastMarkets4h} 4h`,
    trade_records: data.tradeRecords.toLocaleString('en-US'),
    unique_wallets: data.uniqueWallets.toLocaleString('en-US'),
    opportunity_public_count: data.edgeSummary.countLabel,
    opportunity_summary: data.edgeSummary.summary,
    opportunity_categories: data.edgeSummary.categories,
    resolution_distribution: data.edgeSummary.resolutionDistribution,
    avg_tests_per_day: `${data.avgTestsPerDay.toFixed(1)} tests/day`,
    avg_dispatches_per_day: `${data.avgDispatchesPerDay.toFixed(1)} dispatches/day`,
    velocity_span: `${data.velocitySpanDays} day evidence span`,
    commit_count: `${data.commitCount} commits`,
    commit_note: `${data.commitCount} repository commits in the current public history`,
    forecast_cycle: `Cycle ${data.cycleNumber}`,
    forecast_note: data.nextAction,
    next_milestone: data.nextMilestone,
    deploy_blocker: data.deployBlocker,
    a6_summary: `${data.a6AllowedEvents} allowed neg-risk events / ${data.a6QualifiedEvents} qualified live-surface / ${data.a6Executable} executable`,
    b1_summary: `${data.b1Pairs} deterministic pairs in ${data.b1Sample.toLocaleString('en-US')} allowed markets`,
    risk_position: data.risk.positionUsd,
    risk_daily_loss: data.risk.dailyLossUsd,
    risk_kelly: data.risk.kelly,
    risk_open_positions: String(data.risk.maxOpenPositions),
    diary_entries: String(data.diaryEntries),
    generated_date: formatLongDate(data.generatedAt),
    generated_utc: formatUtc(data.generatedAt),
    year: String(new Date().getUTCFullYear())
  };

  Object.entries(values).forEach(([key, value]) => {
    setAll('data-fill', key, value);
  });
}

function setStatusPill(data) {
  const pill = document.querySelector('[data-role="status-pill"]');
  if (!pill) return;
  pill.textContent = data.serviceActive && data.launchBlocked
    ? 'running / blocked / drift'
    : data.serviceActive
      ? 'running / launch clear'
      : 'service stopped / blocked';
  pill.classList.remove('is-good', 'is-bad');
  if (data.serviceActive && !data.launchBlocked) {
    pill.classList.add('is-good');
  } else if (!data.serviceActive) {
    pill.classList.add('is-bad');
  }
}

function setActiveNav() {
  const page = document.body.dataset.page;
  document.querySelectorAll('.nav-link').forEach(link => {
    if (link.dataset.page === page) {
      link.classList.add('is-active');
    }
  });
}

async function loadSiteData() {
  const [
    publicSnapshot,
    runtimeTruth,
    remoteCycleStatus,
    remoteServiceStatus,
    rootTestStatus,
    velocity,
    benchmarkInventory,
    performanceDoc,
    claudeDoc,
    buildSpec,
    arbSnapshot
  ] = await Promise.all([
    fetchJson('/reports/public_runtime_snapshot.json'),
    fetchJson('/reports/runtime_truth_latest.json'),
    fetchJson('/reports/remote_cycle_status.json'),
    fetchJson('/reports/remote_service_status.json'),
    fetchJson('/reports/root_test_status.json'),
    fetchJson('/improvement_velocity.json'),
    fetchJson('/inventory/data/systems.json'),
    fetchText('/docs/PERFORMANCE.md'),
    fetchText('/CLAUDE.md'),
    fetchText('/REPLIT_NEXT_BUILD.md'),
    fetchJson('/reports/arb_empirical_snapshot.json')
  ]);

  const snapshot = publicSnapshot || runtimeTruth || remoteCycleStatus || {};
  const detail = runtimeTruth || publicSnapshot || remoteCycleStatus || {};
  const performance = parsePerformanceMetrics(performanceDoc);
  const risk = parseRiskRails(claudeDoc);
  const signalLanes = parseSignalLaneMetrics(buildSpec);
  const pipelinePath = pick(snapshot, ['latest_pipeline.path'], pick(detail, ['latest_pipeline.path', 'artifacts.latest_pipeline_json'], null));
  const edgePath = pick(snapshot, ['latest_edge_scan.path'], pick(detail, ['latest_edge_scan.path', 'artifacts.latest_edge_scan_json'], null));

  const [pipelineSummary, edgeScan] = await Promise.all([
    fetchJson(rootPath(pipelinePath)),
    fetchJson(rootPath(edgePath))
  ]);
  const detailedPipelinePath = pick(pipelineSummary, ['evidence_paths.detailed_pipeline_json'], null);
  const detailedPipeline = detailedPipelinePath ? await fetchJson(rootPath(detailedPipelinePath)) : null;
  const pipeline = detailedPipeline || pipelineSummary || {};

  const rootVerificationSummary = buildVerificationSummary(rootTestStatus, snapshot);
  const verificationParsed = parseVerificationSummary(rootVerificationSummary);
  const verificationStatus = String(
    pick(rootTestStatus, ['status'], pick(snapshot, ['verification.status'], 'passing'))
  ).toLowerCase();
  const capitalSources = pick(detail, ['capital.sources'], []);
  const polymarketCapital = capitalSources.find(source => source.account === 'Polymarket')?.amount_usd ?? 247.51;
  const kalshiCapital = capitalSources.find(source => source.account === 'Kalshi')?.amount_usd ?? 100.0;
  const blockedChecks = pick(detail, ['launch.blocked_checks'], []);
  const launchReasons = humanizeBlockedChecks(blockedChecks).filter((value, index, array) => array.indexOf(value) === index);
  const fastMarkets = pick(pipeline, ['public_safe_counts.fast_markets'], {});
  const a6Snapshot = pick(pipeline, ['public_safe_counts.a6_b1.a6'], {});
  const b1Snapshot = pick(pipeline, ['public_safe_counts.a6_b1.b1'], {});
  const arbQualified = pick(arbSnapshot, ['live_surface.qualified_a6_count'], 57);
  const edgeSummary = summarizeEdgeScan(edgeScan);
  const strategyCatalog = {
    total: PUBLIC_SITE_SNAPSHOT.strategyTotal,
    deployed: normalizeNumber(pick(velocity, ['trading_agent.strategies_deployed'], DEFAULTS.strategyCatalog.deployed), DEFAULTS.strategyCatalog.deployed),
    building: normalizeNumber(
      pick(velocity, ['trading_agent.strategies_building_total'], pick(velocity, ['trading_agent.strategies_building_core'], DEFAULTS.strategyCatalog.building)),
      DEFAULTS.strategyCatalog.building
    ),
    rejected: normalizeNumber(pick(velocity, ['trading_agent.strategies_rejected'], 10), 10)
      + normalizeNumber(pick(velocity, ['trading_agent.strategies_pre_rejected'], 8), 8),
    pipeline: normalizeNumber(pick(velocity, ['trading_agent.strategies_research_pipeline'], DEFAULTS.strategyCatalog.pipeline), DEFAULTS.strategyCatalog.pipeline),
    reevaluating: normalizeNumber(pick(velocity, ['trading_agent.strategies_re_evaluating'], DEFAULTS.strategyCatalog.reevaluating), DEFAULTS.strategyCatalog.reevaluating)
  };
  const serviceActive = ['running', 'active'].includes(String(pick(snapshot, ['service.status', 'service.detail'], 'running')).toLowerCase())
    || ['running', 'active'].includes(String(pick(detail, ['service.detail', 'service.status'], 'running')).toLowerCase());
  const launchBlocked = Boolean(pick(snapshot, ['launch.live_launch_blocked'], true));
  const serviceStateLabel = serviceActive
    ? 'running'
    : String(pick(snapshot, ['service.status'], 'stopped')).toLowerCase();
  const serviceDriftNote = serviceActive && launchBlocked
    ? 'Treat the active service as drift until paper or shadow mode is confirmed.'
    : serviceActive
      ? 'Remote service posture is aligned with launch state.'
      : 'Remote service is stopped, which matches the current blocked launch posture.';
  const benchmarkedSystems = Array.isArray(benchmarkInventory?.systems)
    ? benchmarkInventory.systems.length
    : DEFAULTS.benchmarkedSystems;
  const verificationBaselineTotal = PUBLIC_SITE_SNAPSHOT.verifiedTestsTotal;
  const cycleNumber = normalizeNumber(
    pick(velocity, ['cycle.number'], pick(detail, ['cycle.number'], DEFAULTS.cycleNumber)),
    DEFAULTS.cycleNumber
  );
  const cycleLabel = pick(velocity, ['cycle.name'], DEFAULTS.cycleLabel).replace(/\s+[—-].*$/, '').trim() || DEFAULTS.cycleLabel;
  const verificationSummary = `${PUBLIC_SITE_SNAPSHOT.verifiedTestsTotal.toLocaleString('en-US')} verified tests`;
  const verificationRootDetail = verificationParsed.failed
    ? `${verificationParsed.failed} failed current root suites`
    : verificationParsed.passedTotal
      ? `${verificationParsed.passedTotal} passed current root suites`
      : rootVerificationSummary;

  return {
    cycleLabel,
    cycleNumber,
    capitalTracked: PUBLIC_SITE_SNAPSHOT.trackedCapitalUsd,
    capitalDeployed: PUBLIC_SITE_SNAPSHOT.deployedCapitalUsd,
    polymarketCapital,
    kalshiCapital,
    cyclesCompleted: PUBLIC_SITE_SNAPSHOT.cyclesCompleted,
    totalTrades: PUBLIC_SITE_SNAPSHOT.totalTrades,
    closedTrades: PUBLIC_SITE_SNAPSHOT.closedTrades,
    walletCount: PUBLIC_SITE_SNAPSHOT.walletCount,
    walletReady: PUBLIC_SITE_SNAPSHOT.walletReady,
    walletStatus: PUBLIC_SITE_SNAPSHOT.walletStatus,
    serviceActive,
    serviceStateLabel,
    serviceSurface: serviceActive && launchBlocked ? 'running (drift)' : serviceStateLabel,
    serviceCheckedAt: pick(snapshot, ['service.checked_at'], pick(detail, ['service.checked_at'], '2026-03-09T01:25:45Z')),
    serviceDriftNote,
    serverLocation: DEFAULTS.server.location,
    serverDetail: DEFAULTS.server.detail,
    launchBlocked,
    launchReasons,
    nextAction: pick(snapshot, ['launch.next_operator_action'], 'Restart jj_live in paper or shadow with conservative caps and collect the first closed trades.'),
    nextMilestone: DEFAULTS.nextMilestone,
    deployBlocker: DEFAULTS.deployBlocker,
    fastVerdict: PUBLIC_SITE_SNAPSHOT.fastVerdict,
    fastMarketsObserved: Number(fastMarkets.total_markets_observed || pick(pipelineSummary, ['markets_scanned'], 75)),
    fastMarkets15m: Number(fastMarkets.markets_15m || 29),
    fastMarkets5m: Number(fastMarkets.markets_5m || 39),
    fastMarkets4h: Number(fastMarkets.markets_4h || 7),
    tradeRecords: Number(fastMarkets.trade_records || 3047),
    uniqueWallets: Number(fastMarkets.unique_wallets || 1715),
    edgeSummary,
    a6AllowedEvents: Number(a6Snapshot.allowed_neg_risk_event_count || 563),
    a6QualifiedEvents: Number(arbQualified || 57),
    a6Executable: Number(a6Snapshot.executable_constructions_below_threshold || 0),
    b1Pairs: Number(b1Snapshot.deterministic_template_pair_count || 0),
    b1Sample: Number(b1Snapshot.allowed_market_sample_size || 1000),
    verificationSummary,
    verificationRootDetail,
    verificationParsed,
    verificationStatus,
    verificationBaselineTotal,
    avgTestsPerDay: Number(pick(velocity, ['velocity_summary.avg_tests_per_day'], 57.1)),
    avgDispatchesPerDay: Number(pick(velocity, ['velocity_summary.avg_dispatches_per_day'], 4.3)),
    velocitySpanDays: Number(pick(velocity, ['velocity_summary.timeline_span_days'], pick(velocity, ['velocity_metrics.project_age_days'], 22))),
    strategyCatalog,
    dispatchWorkOrders: normalizeNumber(pick(velocity, ['contribution_flywheel.dispatch_work_orders'], pick(velocity, ['velocity_metrics.dispatch_work_orders'], DEFAULTS.dispatchWorkOrders)), DEFAULTS.dispatchWorkOrders),
    researchFiles: normalizeNumber(pick(velocity, ['contribution_flywheel.dispatch_markdown_files'], pick(velocity, ['velocity_metrics.dispatch_markdown_files'], DEFAULTS.researchFiles)), DEFAULTS.researchFiles),
    benchmarkedSystems,
    primarySignalLanes: PUBLIC_SITE_SNAPSHOT.primarySignalLanes,
    anomalySignalLanes: PUBLIC_SITE_SNAPSHOT.anomalySignalLanes,
    commitCount: normalizeNumber(pick(velocity, ['contribution_flywheel.commits_total_after_instance'], pick(velocity, ['velocity_metrics.commits_total_after_instance'], DEFAULTS.commitCount)), DEFAULTS.commitCount),
    calibratedWinRate: performance.calibrated,
    legacyWinRate: performance.legacy,
    noOnlyWinRate: `${(normalizeNumber(pick(velocity, ['trading_agent.backtest_win_rate_no_only'], 0.762), 0.762) * 100).toFixed(1)}%`,
    risk,
    diaryEntries: DEFAULTS.diaryEntries,
    generatedAt: pick(snapshot, ['generated_at'], '2026-03-09T01:26:09Z')
  };
}

async function initSite() {
  setActiveNav();
  const data = await loadSiteData();
  setCommonValues(data);
  setStatusPill(data);
}

document.addEventListener('DOMContentLoaded', () => {
  initSite().catch(() => {
    setActiveNav();
  });
});
