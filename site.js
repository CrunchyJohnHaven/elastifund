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
  }
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

async function fetchFirstJson(paths) {
  for (const path of paths) {
    const result = await fetchJson(path);
    if (result) return result;
  }
  return null;
}

function formatNumber(value, maximumFractionDigits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '0';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits,
    minimumFractionDigits: Number.isInteger(number) ? 0 : Math.min(1, maximumFractionDigits)
  }).format(number);
}

function formatCompactNumber(value, maximumFractionDigits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '0';
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits
  }).format(number);
}

function formatUsd(value, digits = 2) {
  const number = Number(value || 0);
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(number);
}

function formatPercent(value, maximumFractionDigits = 1) {
  return `${formatNumber(value, maximumFractionDigits)}%`;
}

function formatCompactPercent(value, maximumFractionDigits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '0%';
  if (Math.abs(number) >= 100000) {
    return `${formatCompactNumber(number, maximumFractionDigits)}%`;
  }
  return formatPercent(number, maximumFractionDigits);
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
  if (!value) return '2026-03-09 20:03 UTC';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '2026-03-09 20:03 UTC';
  return date.toISOString().replace('T', ' ').replace(/\.\d+Z$/, ' UTC');
}

function formatShortUtc(value) {
  if (!value) return 'Mar 9 20:03 UTC';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Mar 9 20:03 UTC';
  const formatted = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC'
  }).format(date);
  return `${formatted} UTC`;
}

function formatHours(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '0.0';
  return number.toFixed(number >= 10 ? 0 : 1);
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
    root_tests_not_passing: 'verification not green',
    accounting_reconciliation_drift: 'ledger and wallet drift',
    polymarket_capital_truth_drift: 'capital reconciliation drift'
  };
  return (checks || []).map(item => labels[item] || item.replace(/_/g, ' '));
}

function summarizeList(items, maxItems = 3) {
  const clean = (items || []).filter(Boolean);
  if (!clean.length) return 'none';
  if (clean.length <= maxItems) return clean.join(', ');
  return `${clean.slice(0, maxItems).join(', ')} +${clean.length - maxItems} more`;
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

function buildFreshness(timestamp) {
  if (!timestamp) {
    return { label: 'freshness unknown', className: 'is-aging' };
  }
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return { label: 'freshness unknown', className: 'is-aging' };
  }
  const ageMs = Date.now() - date.getTime();
  const ageMinutes = Math.max(0, Math.round(ageMs / 60000));
  if (ageMinutes < 60) {
    return { label: `fresh ${ageMinutes}m`, className: 'is-fresh' };
  }
  const ageHours = ageMinutes / 60;
  if (ageHours < 24) {
    return { label: `aging ${ageHours.toFixed(ageHours >= 10 ? 0 : 1)}h`, className: 'is-aging' };
  }
  return { label: `stale ${(ageHours / 24).toFixed(1)}d`, className: 'is-stale' };
}

function minutesSince(timestamp) {
  if (!timestamp) return Number.POSITIVE_INFINITY;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return Number.POSITIVE_INFINITY;
  return Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function toneFromFreshnessClass(className) {
  if (className === 'is-fresh') return 'good';
  if (className === 'is-stale') return 'bad';
  return 'warn';
}

function describeSlaStatus(ageMinutes, slaMinutes) {
  if (!Number.isFinite(ageMinutes)) {
    return { label: 'freshness unknown', tone: 'bad' };
  }
  if (ageMinutes <= slaMinutes) {
    return { label: `within ${formatNumber(slaMinutes, 0)}m SLA`, tone: 'good' };
  }
  if (ageMinutes <= slaMinutes * 3) {
    return { label: `outside ${formatNumber(slaMinutes, 0)}m SLA`, tone: 'warn' };
  }
  return { label: `stale vs ${formatNumber(slaMinutes, 0)}m SLA`, tone: 'bad' };
}

function describeLoopHealth(score) {
  if (score >= 75) {
    return { label: 'Running with usable signal', tone: 'good' };
  }
  if (score >= 45) {
    return { label: 'Degraded but observable', tone: 'warn' };
  }
  return { label: 'Stalled or failing closed', tone: 'bad' };
}

function shorten(text, maxLength = 140) {
  const value = String(text || '').trim();
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trimEnd()}...`;
}

function humanizeClaimStatus(status) {
  const value = String(status || '').toLowerCase();
  if (!value) return 'Unknown';
  if (value.includes('blocked')) return 'Blocked';
  if (value.includes('prelaunch')) return 'Prelaunch instrumentation only';
  if (value.includes('allowed')) return 'Allowed';
  return titleCase(value);
}

function humanizeSource(value) {
  const text = String(value || '').replace(/_/g, ' ').trim();
  return text ? titleCase(text) : 'Unknown source';
}

function formatPercentOrLabel(value, fallback = 'not published') {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? formatPercent(numeric) : fallback;
}

function formatCompactPercentOrLabel(value, fallback = 'not published') {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? formatCompactPercent(numeric) : fallback;
}

function buildJjnFallback() {
  return {
    artifact: 'jjn_public_report',
    generated_at: '2026-03-09T20:03:46.413978+00:00',
    phase: 'Phase 0 launch prep',
    claim_status: 'prelaunch_instrumentation_only',
    claim_reason: 'The Website Growth Audit wedge is coded and safety-gated, but live send, checkout, fulfillment, and KPI loops are not launched.',
    offer: {
      name: 'Website Growth Audit',
      price_range_usd: '$500-$2,500',
      delivery_days: 5,
      fulfillment_type: 'hybrid',
      status: 'implemented_in_code_not_launched'
    },
    funnel: {
      accounts_researched: 0,
      qualified_accounts: 0,
      outreach_approved: 0,
      messages_delivered: 0,
      replies: 0,
      meetings_booked: 0,
      proposals_sent: 0,
      outcomes_recorded: 0,
      revenue_won_usd: 0,
      gross_margin_usd: 0,
      time_to_first_dollar_days: null
    },
    conversion: {},
    activation: {
      current_phase: 'instrumentation_and_approval',
      approval_mode: 'human_review_required',
      send_status: 'blocked_pending_verified_domain_and_explicit_approval',
      fulfillment_status: 'placeholders_defined_not_launched',
      dashboard_status: 'phase0_public_board'
    },
    delivery: {
      checkout_ready: false,
      billing_webhooks_ready: false,
      provisioning_ready: false,
      fulfillment_reporting_ready: false,
      recurring_monitor_defined: true
    },
    evidence: {
      engines_functional: 5,
      templates_count: 3,
      dashboard_count: 1,
      package_tests_passed: 61,
      repo_tests_passed: 49,
      smoke_path_available: true,
      pipeline_status: 'RevenuePipeline runs from the CLI'
    },
    blockers: [
      'Verified sending domain and DNS auth are still missing.',
      'A curated lead source has not been loaded into a live cycle.',
      'Live outreach still requires explicit human approval.',
      'Checkout and billing are not implemented.',
      'Fulfillment reporting and KPI loops are not yet publishing.'
    ]
  };
}

function findArtifact(artifacts, predicate) {
  return (artifacts || []).find(predicate) || null;
}

function setAll(attribute, key, value) {
  document.querySelectorAll(`[${attribute}="${key}"]`).forEach(element => {
    element.textContent = value;
  });
}

function setFreshnessBadge(key, freshness) {
  document.querySelectorAll(`[data-freshness-badge="${key}"]`).forEach(element => {
    element.textContent = freshness.label;
    element.classList.remove('is-fresh', 'is-aging', 'is-stale');
    element.classList.add(freshness.className);
  });
}

function setToneClass(elements, tone, baseClass = 'neutral') {
  elements.forEach(element => {
    element.classList.remove('good', 'warn', 'bad', 'neutral', 'is-good', 'is-warn', 'is-bad');
    if (element.classList.contains('tag')) {
      element.classList.add(tone || baseClass);
    } else {
      element.classList.add(`is-${tone || 'warn'}`);
    }
  });
}

function setCommonValues(data) {
  const values = {
    cycle_label: data.cycleLabel,
    current_system_arr: `${formatPercent(data.currentSystemArrPct)} realized`,
    current_system_arr_value: formatPercent(data.currentSystemArrPct),
    runtime_cycles: formatNumber(data.cyclesCompleted, 0),
    live_trades: formatNumber(data.totalTrades, 0),
    wallet_count: formatNumber(data.walletCount, 0),
    wallet_status: data.walletReady ? 'ready' : data.walletStatus,
    strategy_total: formatNumber(data.strategyCatalog.total, 0),
    strategy_distribution: `${data.strategyCatalog.deployed} deployed / ${data.strategyCatalog.building} building / ${data.strategyCatalog.rejected} rejected / ${data.strategyCatalog.pipeline} pipeline${data.strategyCatalog.reevaluating ? ` (+${data.strategyCatalog.reevaluating} re-evaluating)` : ''}`,
    dispatch_orders: formatNumber(data.dispatchWorkOrders, 0),
    dispatch_work_orders: formatNumber(data.dispatchWorkOrders, 0),
    dispatch_archive: formatNumber(data.researchFiles, 0),
    research_files: formatNumber(data.researchFiles, 0),
    benchmarked_systems: formatNumber(data.benchmarkedSystems, 0),
    signal_lane_total: formatNumber(data.primarySignalLanes + data.anomalySignalLanes, 0),
    signal_lanes: `${data.primarySignalLanes + data.anomalySignalLanes} total (${data.primarySignalLanes} primary + ${data.anomalySignalLanes} anomaly)`,
    calibrated_win_rate: data.calibratedWinRate,
    legacy_win_rate: data.legacyWinRate,
    no_only_win_rate: data.noOnlyWinRate,
    verification_summary: data.verificationSummary,
    verification_current: `${formatNumber(data.verificationBaselineTotal, 0)} checked`,
    verification_baseline: `${formatNumber(data.verificationBaselineTotal, 0)} passed in the latest checked-in suite snapshot`,
    verification_root: data.verificationRootDetail,
    service_state: data.serviceStateLabel,
    service_surface: data.runtimeSplitSummary,
    service_checked_at: formatUtc(data.serviceCheckedAt),
    service_drift_note: data.serviceDriftNote,
    server_location: data.serverLocation,
    server_detail: data.serverDetail,
    launch_posture: data.launchBlocked ? 'launch blocked' : 'launch clear',
    launch_reasons: data.launchReasonsSummary,
    next_action: data.nextAction,
    fast_verdict: data.fastVerdict,
    fast_markets: formatNumber(data.fastMarketsObserved, 0),
    fast_breakdown: `${formatNumber(data.fastMarkets15m, 0)} 15m / ${formatNumber(data.fastMarkets5m, 0)} 5m / ${formatNumber(data.fastMarkets4h, 0)} 4h`,
    trade_records: formatNumber(data.tradeRecords, 0),
    unique_wallets: formatNumber(data.uniqueWallets, 0),
    opportunity_public_count: data.edgeSummary.countLabel,
    opportunity_summary: data.edgeSummary.summary,
    opportunity_categories: data.edgeSummary.categories,
    resolution_distribution: data.edgeSummary.resolutionDistribution,
    avg_tests_per_day: `${formatNumber(data.avgTestsPerDay)} tests/day`,
    avg_dispatches_per_day: `${formatNumber(data.avgDispatchesPerDay)} dispatches/day`,
    velocity_span: `${formatNumber(data.velocitySpanDays, 0)} day evidence span`,
    commit_count: `${formatNumber(data.commitCount, 0)} commits`,
    forecast_cycle: `Cycle ${data.cycleNumber}`,
    forecast_note: data.nextAction,
    next_milestone: 'Dedicated BTC5 sleeve proof',
    deploy_blocker: data.fundClaimReasonShort,
    a6_summary: `${formatNumber(data.a6AllowedEvents, 0)} allowed neg-risk events / ${formatNumber(data.a6QualifiedEvents, 0)} qualified live-surface / ${formatNumber(data.a6Executable, 0)} executable`,
    b1_summary: `${formatNumber(data.b1Pairs, 0)} deterministic pairs in ${formatNumber(data.b1Sample, 0)} allowed markets`,
    risk_position: data.risk.positionUsd,
    risk_daily_loss: data.risk.dailyLossUsd,
    risk_kelly: data.risk.kelly,
    risk_open_positions: formatNumber(data.risk.maxOpenPositions, 0),
    diary_entries: formatNumber(data.diaryEntries, 0),
    generated_date: formatLongDate(data.generatedAt),
    generated_utc: formatUtc(data.generatedAt),
    year: String(new Date().getUTCFullYear()),
    runtime_split_summary: data.runtimeSplitSummary,
    headline_summary: data.headlineSummary,
    fund_claim_status: data.fundClaimStatusLabel,
    fund_claim_reason: data.fundClaimReason,
    fund_claim_reason_short: data.fundClaimReasonShort,
    btc5_live_pnl: formatUsd(data.btc5LiveFilledPnlUsd),
    btc5_live_rows: formatNumber(data.btc5LiveFilledRows, 0),
    btc5_latest_fill: formatUtc(data.btc5LatestFillAt),
    btc5_source_label: data.btc5SourceLabel,
    btc5_source_path: data.btc5DbPath,
    btc5_best_bucket: data.btc5BestBucket,
    btc5_best_bucket_pnl: formatUsd(data.btc5BestBucketPnlUsd),
    btc5_best_direction: data.btc5BestDirection,
    btc5_best_direction_pnl: formatUsd(data.btc5BestDirectionPnlUsd),
    btc5_guardrails: data.btc5Guardrails,
    btc5_latest_order_status: data.btc5LatestOrderStatus,
    btc5_run_rate: data.btc5RunRateCompact,
    btc5_run_rate_exact: data.btc5RunRateExact,
    btc5_window_fills: formatNumber(data.btc5WindowLiveFills, 0),
    btc5_window_hours: formatHours(data.btc5WindowHours),
    btc5_window_pnl: formatUsd(data.btc5WindowPnlUsd),
    forecast_arr: data.forecastArrCompact,
    forecast_arr_exact: data.forecastArrExact,
    forecast_best_arr: data.forecastBestArrCompact,
    forecast_delta: data.forecastDeltaCompact,
    forecast_delta_exact: data.forecastDeltaExact,
    forecast_confidence: data.forecastConfidenceLabel,
    forecast_confidence_reasons: data.forecastConfidenceReasons,
    forecast_source: data.forecastSourcePath,
    deploy_recommendation: data.deployRecommendationLabel,
    velocity_window_hours: formatHours(data.velocityWindowHours),
    velocity_cycles: formatNumber(data.velocityCycles, 0),
    velocity_window_summary: data.velocityWindowHours > 0
      ? `${formatNumber(data.velocityCycles, 0)} cycles over ${formatHours(data.velocityWindowHours)}h`
      : 'no current forecast window published',
    velocity_gain: data.velocityGainCompact,
    velocity_gain_exact: data.velocityGainExact,
    velocity_per_day: data.velocityPerDayCompact,
    velocity_fill_growth: `+${formatNumber(data.velocityFillGrowth, 0)} validation fills`,
    velocity_confidence: data.velocityConfidenceLabel,
    loop_health_label: data.loopHealthLabel,
    loop_health_tag: data.loopHealthTag,
    loop_health_summary: data.loopHealthSummary,
    loop_freshness_status: data.loopFreshnessStatus,
    loop_staleness_summary: data.loopStalenessSummary,
    loop_primary_blocker: data.loopPrimaryBlocker,
    loop_operator_action: data.loopOperatorAction,
    loop_learning_status: data.loopLearningStatus,
    loop_learning_summary: data.loopLearningSummary,
    loop_attribution_status: data.loopAttributionStatus,
    loop_attribution_summary: data.loopAttributionSummary,
    loop_search_summary: data.loopSearchSummary,
    loop_execution_status: data.loopExecutionStatus,
    loop_execution_summary: data.loopExecutionSummary,
    loop_visual_packets: data.loopVisualPackets,
    loop_visual_summary: data.loopVisualSummary,
    loop_core_note: data.loopCoreNote,
    loop_trend_summary: data.loopTrendSummary,
    loop_trend_start_label: data.loopTrendStartLabel,
    loop_trend_end_label: data.loopTrendEndLabel,
    loop_stage_search_status: data.loopStages.search.label,
    loop_stage_search_summary: data.loopStages.search.summary,
    loop_stage_evidence_status: data.loopStages.evidence.label,
    loop_stage_evidence_summary: data.loopStages.evidence.summary,
    loop_stage_gate_status: data.loopStages.gate.label,
    loop_stage_gate_summary: data.loopStages.gate.summary,
    loop_stage_execution_status: data.loopStages.execution.label,
    loop_stage_execution_summary: data.loopStages.execution.summary,
    loop_stage_learning_status: data.loopStages.learning.label,
    loop_stage_learning_summary: data.loopStages.learning.summary,
    wallet_open_positions: formatNumber(data.walletOpenPositions, 0),
    wallet_closed_positions: formatNumber(data.walletClosedPositions, 0),
    wallet_realized_pnl: formatUsd(data.walletRealizedPnlUsd),
    jjn_phase: data.jjnPhase,
    jjn_current_phase_label: data.jjnCurrentPhaseLabel,
    jjn_claim_status: data.jjnClaimStatusLabel,
    jjn_claim_reason: data.jjnClaimReason,
    jjn_offer_name: data.jjnOfferName,
    jjn_offer_price: data.jjnOfferPrice,
    jjn_offer_delivery: `${formatNumber(data.jjnOfferDeliveryDays, 0)} day delivery`,
    jjn_offer_status: data.jjnOfferStatusLabel,
    jjn_approval_mode: data.jjnApprovalModeLabel,
    jjn_send_status: data.jjnSendStatusLabel,
    jjn_fulfillment_status: data.jjnFulfillmentStatusLabel,
    jjn_engines_functional: formatNumber(data.jjnEnginesFunctional, 0),
    jjn_templates_count: formatNumber(data.jjnTemplatesCount, 0),
    jjn_dashboard_count: formatNumber(data.jjnDashboardCount, 0),
    jjn_package_tests: formatNumber(data.jjnPackageTests, 0),
    jjn_repo_tests: formatNumber(data.jjnRepoTests, 0),
    jjn_accounts_researched: formatNumber(data.jjnAccountsResearched, 0),
    jjn_qualified_accounts: formatNumber(data.jjnQualifiedAccounts, 0),
    jjn_outreach_approved: formatNumber(data.jjnOutreachApproved, 0),
    jjn_messages_delivered: formatNumber(data.jjnMessagesDelivered, 0),
    jjn_replies: formatNumber(data.jjnReplies, 0),
    jjn_meetings_booked: formatNumber(data.jjnMeetingsBooked, 0),
    jjn_proposals_sent: formatNumber(data.jjnProposalsSent, 0),
    jjn_outcomes_recorded: formatNumber(data.jjnOutcomesRecorded, 0),
    jjn_revenue_won: formatUsd(data.jjnRevenueWonUsd),
    jjn_gross_margin: formatUsd(data.jjnGrossMarginUsd),
    jjn_time_to_first_dollar: data.jjnTimeToFirstDollar,
    jjn_reply_rate: data.jjnReplyRate,
    jjn_blockers_short: data.jjnBlockersShort,
    snapshot_source: data.snapshotSource,
    elastic_shared_substrate_summary: data.elasticSharedSubstrateSummary,
    elastic_worker_family_coverage: data.elasticWorkerFamilyCoverage,
    elastic_artifact_backed_proof: data.elasticArtifactBackedProof,
    elastic_operator_surface_summary: data.elasticOperatorSurfaceSummary,
    elastic_publish_loop_summary: data.elasticPublishLoopSummary,
    elastic_public_scope_guardrail: data.elasticPublicScopeGuardrail,
    elastic_employee_path_live: data.elasticEmployeePathLive,
    elastic_employee_path_repo: data.elasticEmployeePathRepo,
    elastic_employee_path_develop: data.elasticEmployeePathDevelop,
    elastic_employee_path_contribute: data.elasticEmployeePathContribute,
    elastic_employee_path_summary: data.elasticEmployeePathSummary
  };

  Object.entries(values).forEach(([key, value]) => {
    setAll('data-fill', key, value);
  });

  setFreshnessBadge('snapshot', data.snapshotFreshness);
  setFreshnessBadge('btc5', data.btc5Freshness);
  setFreshnessBadge('forecast', data.forecastFreshness);
  setFreshnessBadge('jjn', data.jjnFreshness);
}

function createNode(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function findSectionByKicker(kickerText) {
  return Array.from(document.querySelectorAll('.page-section')).find(section => {
    const kicker = section.querySelector('.section-kicker');
    return kicker && kicker.textContent.trim() === kickerText;
  }) || null;
}

function findCardByKicker(kickerText) {
  return Array.from(document.querySelectorAll('.card, .proof-card, .path-card, .surface-card')).find(card => {
    const kicker = card.querySelector('.card-kicker, .panel-kicker, .path-kicker');
    return kicker && kicker.textContent.trim() === kickerText;
  }) || null;
}

function applyElasticEnhancements(data) {
  if (document.body?.dataset?.page !== 'elastic') {
    return;
  }

  const proofPanel = document.querySelector('.route-hero .proof-card');
  const proofCopy = proofPanel?.querySelector('.card-copy');
  if (proofPanel) {
    proofPanel.classList.add('elastic-proof-panel');
  }
  if (proofCopy) {
    proofCopy.textContent = data.elasticArtifactBackedProof;
  }

  const architectureSection = findSectionByKicker('Elastic in the middle');
  const architectureCard = architectureSection?.querySelector('.card');
  const architectureDiagram = architectureCard?.querySelector('.diagram');

  if (architectureSection) {
    architectureSection.classList.add('elastic-architecture-section');
  }
  if (architectureCard) {
    architectureCard.classList.add('elastic-architecture-card');
    if (!architectureCard.querySelector('.elastic-architecture-banner')) {
      const banner = createNode('div', 'elastic-architecture-banner');
      const intro = createNode('div', 'elastic-architecture-intro');
      const introKicker = createNode('div', 'panel-kicker', 'Shared substrate');
      const introSummary = createNode('p', 'elastic-architecture-summary', data.elasticSharedSubstrateSummary);
      intro.append(introKicker, introSummary);
      banner.appendChild(intro);

      [
        ['Worker coverage', data.elasticWorkerFamilyCoverage],
        ['Artifact proof', data.elasticArtifactBackedProof],
        ['Public scope', data.elasticPublicScopeGuardrail]
      ].forEach(([label, value]) => {
        const pill = createNode('div', 'elastic-architecture-pill');
        const pillLabel = createNode('div', 'elastic-architecture-pill-label', label);
        const pillValue = createNode('div', 'elastic-architecture-pill-value', value);
        pill.append(pillLabel, pillValue);
        banner.appendChild(pill);
      });

      architectureCard.insertBefore(banner, architectureCard.firstChild);
    }
  }
  if (architectureDiagram) {
    architectureDiagram.classList.add('elastic-architecture-diagram');
    Array.from(architectureDiagram.children).forEach((step, index) => {
      step.classList.add('elastic-architecture-step');
      if (index === 1) {
        step.classList.add('is-core');
      }
    });
  }

  const publishingCard = findCardByKicker('Public publishing loop');
  const publishingCopy = publishingCard?.querySelector('.card-copy');
  if (publishingCard) {
    publishingCard.classList.add('elastic-publishing-card');
  }
  if (publishingCopy) {
    publishingCopy.textContent = data.elasticPublishLoopSummary;
  }

  const evidenceSection = findSectionByKicker('What Elastic is doing in this system today');
  const evidenceGrid = evidenceSection?.querySelector('.surface-grid');
  const evidenceCopy = evidenceSection?.querySelector('.section-copy');
  if (evidenceSection) {
    evidenceSection.classList.add('elastic-evidence-section');
  }
  if (evidenceCopy) {
    evidenceCopy.textContent = data.elasticOperatorSurfaceSummary;
  }
  if (evidenceGrid) {
    evidenceGrid.classList.add('elastic-evidence-grid');
    Array.from(evidenceGrid.children).forEach((card, index) => {
      card.classList.add('elastic-evidence-card');
      if (index === 0) {
        card.classList.add('is-featured');
      }
    });
  }

  const nextStepsSection = findSectionByKicker('What an Elastic employee can do next');
  const sectionHeader = nextStepsSection?.querySelector('.section-header');
  const pathGrid = nextStepsSection?.querySelector('.path-grid');
  if (pathGrid) {
    pathGrid.classList.add('elastic-path-grid');
  }
  if (sectionHeader && pathGrid && !nextStepsSection.querySelector('.elastic-cta-strip')) {
    const strip = createNode('div', 'elastic-cta-strip');
    [
      data.elasticEmployeePathLive,
      data.elasticEmployeePathRepo,
      data.elasticEmployeePathDevelop,
      data.elasticEmployeePathContribute
    ].forEach(label => {
      strip.appendChild(createNode('span', 'elastic-cta-pill', label));
    });
    sectionHeader.insertAdjacentElement('afterend', strip);
  }
}

function applyLiveEnhancements(data) {
  if (document.body?.dataset?.page !== 'live') {
    return;
  }

  setToneClass(Array.from(document.querySelectorAll('[data-loop-health-tag]')), data.loopHealthTone);

  document.querySelectorAll('[data-loop-health-fill]').forEach(element => {
    element.style.width = `${clamp(data.loopHealthScore, 0, 100)}%`;
    element.classList.remove('is-good', 'is-warn', 'is-bad');
    element.classList.add(`is-${data.loopHealthTone}`);
  });

  Object.entries(data.loopStages).forEach(([stage, stageData]) => {
    setToneClass(Array.from(document.querySelectorAll(`[data-loop-stage-badge="${stage}"]`)), stageData.tone);
    setToneClass(Array.from(document.querySelectorAll(`[data-loop-orbit-badge="${stage}"]`)), stageData.tone);
    document.querySelectorAll(`[data-loop-stage="${stage}"]`).forEach(element => {
      element.classList.remove('is-good', 'is-warn', 'is-bad');
      element.classList.add(`is-${stageData.tone}`);
    });
    document.querySelectorAll(`[data-loop-orbit-node="${stage}"]`).forEach(element => {
      element.classList.remove('is-good', 'is-warn', 'is-bad');
      element.classList.add(`is-${stageData.tone}`);
    });
  });

  const particleHost = document.querySelector('[data-loop-particles]');
  if (particleHost) {
    particleHost.innerHTML = '';
    data.loopParticleTones.forEach((tone, index) => {
      const particle = createNode('div', `loop-particle is-${tone}`);
      particle.style.setProperty('--duration', `${12 + (index % 4) * 2}s`);
      particle.style.setProperty('--delay', `${(index * -1.2).toFixed(1)}s`);
      particle.style.setProperty('--start', `${index * (360 / Math.max(data.loopParticleTones.length, 1))}deg`);
      particle.style.setProperty('--size', `${10 + (index % 3) * 2}px`);
      particle.appendChild(createNode('span', 'loop-particle-dot'));
      particleHost.appendChild(particle);
    });
  }

  const trendHost = document.querySelector('[data-loop-trend-chart]');
  if (trendHost) {
    const series = Array.isArray(data.loopTrendSeries) ? data.loopTrendSeries : [];
    if (!series.length) {
      trendHost.innerHTML = '<div class="tiny">No checked-in forecast trace published yet.</div>';
    } else {
      const width = 560;
      const height = 220;
      const padding = 22;
      const values = series.flatMap(point => [point.active, point.best]);
      const minValue = Math.min(...values);
      const maxValue = Math.max(...values);
      const valueSpan = Math.max(1, maxValue - minValue);
      const xStep = series.length > 1 ? (width - padding * 2) / (series.length - 1) : 0;
      const xForIndex = index => padding + xStep * index;
      const yForValue = value => height - padding - (((value - minValue) / valueSpan) * (height - padding * 2));
      const pathFor = key => series.map((point, index) => `${index === 0 ? 'M' : 'L'} ${xForIndex(index).toFixed(2)} ${yForValue(point[key]).toFixed(2)}`).join(' ');
      const maxFills = Math.max(1, ...series.map(point => point.fills));
      const bars = series.map((point, index) => {
        const barHeight = (point.fills / maxFills) * 42;
        const x = xForIndex(index) - 8;
        const y = height - padding - barHeight;
        return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="16" height="${barHeight.toFixed(2)}" rx="6"></rect>`;
      }).join('');
      const points = series.map((point, index) => {
        const cx = xForIndex(index).toFixed(2);
        return `<circle cx="${cx}" cy="${yForValue(point.active).toFixed(2)}" r="3.8"></circle>`;
      }).join('');

      trendHost.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Forecast trend trace">
          <defs>
            <linearGradient id="activeForecastGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#0b8f8b"></stop>
              <stop offset="100%" stop-color="#1e7a46"></stop>
            </linearGradient>
            <linearGradient id="bestForecastGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#b65b1d"></stop>
              <stop offset="100%" stop-color="#b26d00"></stop>
            </linearGradient>
          </defs>
          <g class="trend-grid">
            <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}"></line>
            <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}"></line>
          </g>
          <g class="trend-bars">${bars}</g>
          <path class="trend-line best" d="${pathFor('best')}"></path>
          <path class="trend-line active" d="${pathFor('active')}"></path>
          <g class="trend-points">${points}</g>
        </svg>
      `;
    }
  }
}

function setStatusPill(data) {
  const pill = document.querySelector('[data-role="status-pill"]');
  if (!pill) return;
  pill.classList.remove('is-good', 'is-bad', 'is-warn');

  if (data.btc5LiveFilledRows > 0 && data.launchBlocked) {
    pill.textContent = 'btc5 live / fund blocked';
    pill.classList.add('is-warn');
    return;
  }

  if (!data.launchBlocked && data.serviceActive) {
    pill.textContent = 'launch clear';
    pill.classList.add('is-good');
    return;
  }

  if (!data.serviceActive) {
    pill.textContent = 'service stopped / blocked';
    pill.classList.add('is-bad');
    return;
  }

  pill.textContent = 'runtime syncing';
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
    rootTestStatus,
    velocity,
    benchmarkInventory,
    arbSnapshot,
    jjnReport
  ] = await Promise.all([
    fetchJson('/reports/public_runtime_snapshot.json'),
    fetchJson('/reports/runtime_truth_latest.json'),
    fetchJson('/reports/remote_cycle_status.json'),
    fetchJson('/reports/root_test_status.json'),
    fetchJson('/improvement_velocity.json'),
    fetchJson('/inventory/data/systems.json'),
    fetchJson('/reports/arb_empirical_snapshot.json'),
    fetchFirstJson(['/jjn_public_report.json', '/reports/jjn_public_report.json'])
  ]);

  const snapshot = publicSnapshot || runtimeTruth || remoteCycleStatus || {};
  const detail = runtimeTruth || remoteCycleStatus || publicSnapshot || {};
  const jjn = jjnReport || buildJjnFallback();

  const pipelinePath = pick(snapshot, ['latest_pipeline.path'], pick(detail, ['latest_pipeline.path', 'artifacts.latest_pipeline_json'], null));
  const edgePath = pick(snapshot, ['latest_edge_scan.path'], pick(detail, ['latest_edge_scan.path', 'artifacts.latest_edge_scan_json'], null));

  const [pipelineSummary, edgeScan] = await Promise.all([
    fetchJson(rootPath(pipelinePath)),
    fetchJson(rootPath(edgePath))
  ]);

  const detailedPipelinePath = pick(pipelineSummary, ['evidence_paths.detailed_pipeline_json'], null);
  const detailedPipeline = detailedPipelinePath ? await fetchJson(rootPath(detailedPipelinePath)) : null;
  const pipeline = detailedPipeline || pipelineSummary || {};

  const sourceArtifacts = Array.isArray(velocity?.source_artifacts) ? velocity.source_artifacts : [];
  const scoreboard = pick(velocity, ['scoreboard'], pick(snapshot, ['scoreboard'], pick(detail, ['scoreboard'], {})));
  const timeboundVelocity = pick(velocity, ['timebound_velocity'], pick(snapshot, ['timebound_velocity'], {}));
  const headline = pick(velocity, ['headline'], {});
  const confidence = pick(velocity, ['confidence'], {});
  const runtime = pick(detail, ['runtime'], pick(snapshot, ['runtime'], {}));
  const maker = pick(detail, ['btc_5min_maker'], pick(snapshot, ['btc_5min_maker'], {}));
  const wallet = pick(detail, ['polymarket_wallet'], pick(snapshot, ['polymarket_wallet'], {}));
  const launch = pick(detail, ['launch'], pick(snapshot, ['launch'], {}));
  const service = pick(detail, ['service'], pick(snapshot, ['service'], {}));
  const fastMarkets = pick(pipeline, ['public_safe_counts.fast_markets'], {});
  const a6Snapshot = pick(pipeline, ['public_safe_counts.a6_b1.a6'], {});
  const b1Snapshot = pick(pipeline, ['public_safe_counts.a6_b1.b1'], {});
  const arbQualified = pick(arbSnapshot, ['live_surface.qualified_a6_count'], 57);
  const edgeSummary = summarizeEdgeScan(edgeScan);
  const bestPriceBucket = pick(maker, ['fill_attribution.best_price_bucket.label'], pick(runtime, ['btc5_best_price_bucket'], '<0.49'));
  const bestPriceBucketPnlUsd = pick(maker, ['fill_attribution.best_price_bucket.pnl_usd'], pick(runtime, ['btc5_best_price_bucket_pnl_usd'], 0));
  const bestDirection = pick(maker, ['fill_attribution.best_direction.label'], pick(runtime, ['btc5_best_direction'], 'DOWN'));
  const bestDirectionPnlUsd = pick(maker, ['fill_attribution.best_direction.pnl_usd'], pick(runtime, ['btc5_best_direction_pnl_usd'], 0));
  const guardrail = pick(maker, ['guardrail_recommendation'], pick(runtime, ['btc5_guardrail_recommendation'], {}));
  const blockedChecks = pick(launch, ['blocked_checks'], []);
  const launchReasons = humanizeBlockedChecks(blockedChecks).filter((value, index, array) => array.indexOf(value) === index);
  const rootVerificationSummary = buildVerificationSummary(rootTestStatus, snapshot);
  const verificationParsed = parseVerificationSummary(rootVerificationSummary);
  const benchmarkedSystems = Array.isArray(benchmarkInventory?.systems)
    ? benchmarkInventory.systems.length
    : DEFAULTS.benchmarkedSystems;
  const forecastSourcePath = pick(
    scoreboard,
    ['public_forecast_source_artifact'],
    pick(timeboundVelocity, ['source_artifact'], 'reports/btc5_autoresearch_current_probe/latest.json')
  );
  const forecastArtifact = findArtifact(sourceArtifacts, artifact => artifact.path === forecastSourcePath)
    || findArtifact(sourceArtifacts, artifact => String(artifact.source_class || '').includes('forecast'));
  const generatedAt = pick(snapshot, ['generated_at'], pick(detail, ['generated_at'], pick(velocity, ['generated_at'], '2026-03-09T20:03:46.413978+00:00')));
  const jjnEvidence = pick(jjn, ['evidence'], {});
  const jjnFunnel = pick(jjn, ['funnel'], {});
  const jjnActivation = pick(jjn, ['activation'], {});
  const jjnOffer = pick(jjn, ['offer'], {});
  const forecastTrendSeries = Array.isArray(pick(velocity, ['chart_series.forecast_arr_trend'], []))
    ? pick(velocity, ['chart_series.forecast_arr_trend'], []).map(point => ({
      timestamp: point.timestamp,
      active: normalizeNumber(point.active_forecast_arr_pct, 0),
      best: normalizeNumber(point.best_forecast_arr_pct, 0),
      fills: normalizeNumber(point.live_filled_rows, 0)
    }))
    : [];

  const strategyCatalog = {
    total: normalizeNumber(pick(velocity, ['trading_agent.strategies_total'], DEFAULTS.strategyCatalog.total), DEFAULTS.strategyCatalog.total),
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

  const serviceStatus = String(pick(service, ['status'], pick(detail, ['service_state'], 'stopped'))).toLowerCase();
  const serviceActive = ['running', 'active'].includes(serviceStatus);
  const serviceStateLabel = serviceStatus || 'stopped';
  const serviceCheckedAt = pick(service, ['checked_at'], generatedAt);
  const btc5LiveFilledRows = normalizeNumber(
    pick(scoreboard, ['btc5_live_filled_rows_total'], pick(maker, ['live_filled_rows'], pick(runtime, ['btc5_live_filled_rows'], 0))),
    0
  );
  const launchBlocked = Boolean(pick(launch, ['live_launch_blocked'], true));
  const currentSystemArrPct = normalizeNumber(pick(scoreboard, ['fund_realized_arr_pct'], 0), 0);
  const fundClaimReason = pick(
    scoreboard,
    ['fund_realized_arr_claim_reason'],
    'Ledger and wallet reconciliation remain open, so fund-level realized ARR stays blocked.'
  );
  const velocityMetrics = pick(velocity, ['velocity_metrics'], {});
  const contributionFlywheel = pick(velocity, ['contribution_flywheel'], {});
  const verificationBaselineTotal = verificationParsed.passedTotal || 1165;
  const cycleNumber = normalizeNumber(pick(velocity, ['cycle.number'], pick(detail, ['cycle.number'], DEFAULTS.cycleNumber)), DEFAULTS.cycleNumber);
  const cycleLabel = pick(velocity, ['cycle.name'], DEFAULTS.cycleLabel).replace(/\s+[--].*$/, '').trim() || DEFAULTS.cycleLabel;
  const btc5LiveFilledPnlUsd = normalizeNumber(
    pick(scoreboard, ['btc5_live_filled_pnl_usd_total'], pick(maker, ['live_filled_pnl_usd'], pick(runtime, ['btc5_live_filled_pnl_usd'], 0))),
    0
  );
  const btc5WindowPnlUsd = normalizeNumber(pick(scoreboard, ['realized_btc5_sleeve_window_pnl_usd'], 0), 0);
  const btc5WindowHours = normalizeNumber(pick(scoreboard, ['realized_btc5_sleeve_window_hours'], 0), 0);
  const btc5WindowLiveFills = normalizeNumber(pick(scoreboard, ['realized_btc5_sleeve_window_live_fills'], 0), 0);
  const forecastArrPct = normalizeNumber(pick(scoreboard, ['active_forecast_arr_pct'], 0), 0);
  const forecastBestArrPct = normalizeNumber(pick(scoreboard, ['best_package_forecast_arr_pct'], forecastArrPct), forecastArrPct);
  const forecastDeltaPct = normalizeNumber(pick(scoreboard, ['forecast_arr_delta_pct'], 0), 0);
  const velocityGainPct = normalizeNumber(pick(timeboundVelocity, ['forecast_arr_gain_pct'], forecastDeltaPct), forecastDeltaPct);
  const velocityPerDayPct = normalizeNumber(pick(timeboundVelocity, ['forecast_arr_gain_pct_per_day'], 0), 0);
  const velocityWindowHours = normalizeNumber(pick(timeboundVelocity, ['window_hours'], 0), 0);
  const velocityCycles = normalizeNumber(pick(timeboundVelocity, ['cycles_in_window'], 0), 0);
  const velocityFillGrowth = normalizeNumber(pick(timeboundVelocity, ['validation_fill_growth'], 0), 0);
  const dispatchWorkOrders = normalizeNumber(pick(contributionFlywheel, ['dispatch_work_orders'], DEFAULTS.dispatchWorkOrders), DEFAULTS.dispatchWorkOrders);
  const researchFiles = normalizeNumber(pick(contributionFlywheel, ['dispatch_markdown_files'], DEFAULTS.researchFiles), DEFAULTS.researchFiles);
  const commitCount = normalizeNumber(pick(contributionFlywheel, ['commits_total_after_instance'], DEFAULTS.commitCount), DEFAULTS.commitCount);
  const jjnOfferName = pick(jjnOffer, ['name'], 'Website Growth Audit');
  const totalSignalLanes = DEFAULTS.primarySignalLanes + DEFAULTS.anomalySignalLanes;
  const elasticSharedSubstrateSummary = `Trading workers, JJ-N (${jjnOfferName}), evaluation, and public publishing all write into one Elastic-backed evidence layer.`;
  const elasticWorkerFamilyCoverage = `${formatNumber(totalSignalLanes, 0)} signal lanes + JJ-N (${jjnOfferName}) + checked-in publishing loop`;
  const elasticArtifactBackedProof = `${formatNumber(strategyCatalog.total, 0)} tracked strategies, ${formatNumber(dispatchWorkOrders, 0)} active work-orders, ${formatNumber(btc5LiveFilledRows, 0)} BTC5 live-filled rows, and JJ-N reports keep the story anchored to sanitized checked-in artifacts.`;
  const elasticOperatorSurfaceSummary = 'Searchable artifacts, telemetry, traces, anomaly signals, and operator dashboards stay legible through public-safe outputs rather than browser-side Elastic access.';
  const elasticPublishLoopSummary = 'The site, README, docs, and leaderboards stay strongest when they read checked-in contracts instead of direct Elastic browser sessions.';
  const elasticPublicScopeGuardrail = 'Sanitized checked-in artifacts only';
  const elasticEmployeePathLive = 'Inspect /live/';
  const elasticEmployeePathRepo = 'Read repo evidence';
  const elasticEmployeePathDevelop = 'Boot paper mode';
  const elasticEmployeePathContribute = 'Patch one lane';
  const walletClosedPositions = normalizeNumber(
    pick(runtime, ['polymarket_closed_positions'], pick(wallet, ['closed_positions_count'], 0)),
    0
  );
  const snapshotFreshness = buildFreshness(generatedAt);
  const serviceFreshness = buildFreshness(serviceCheckedAt);
  const btc5CheckedAt = pick(maker, ['checked_at'], pick(maker, ['latest_live_filled_at'], generatedAt));
  const btc5LatestFillAt = pick(maker, ['latest_live_filled_at'], pick(runtime, ['btc5_checked_at'], generatedAt));
  const btc5Freshness = buildFreshness(btc5CheckedAt);
  const forecastCheckedAt = pick(forecastArtifact, ['generated_at'], pick(timeboundVelocity, ['window_ended_at'], generatedAt));
  const forecastFreshness = buildFreshness(forecastCheckedAt);
  const jjnGeneratedAt = pick(jjn, ['generated_at'], generatedAt);
  const jjnFreshness = buildFreshness(jjnGeneratedAt);
  const freshnessSlaMinutes = normalizeNumber(pick(remoteCycleStatus, ['pull_policy.freshness_sla_minutes'], 45), 45);
  const serviceAgeMinutes = minutesSince(serviceCheckedAt);
  const snapshotAgeMinutes = minutesSince(generatedAt);
  const btc5AgeMinutes = minutesSince(btc5LatestFillAt);
  const forecastAgeMinutes = minutesSince(forecastCheckedAt);
  const rootTestAgeMinutes = minutesSince(pick(rootTestStatus, ['checked_at'], generatedAt));
  const freshnessSlaStatus = describeSlaStatus(Math.max(serviceAgeMinutes, snapshotAgeMinutes), freshnessSlaMinutes);
  const verificationFailedCount = verificationParsed.failed || 0;
  const primaryBlocker = launchReasons[0]
    || (verificationFailedCount ? `${verificationFailedCount} failing root tests` : null)
    || (!serviceActive ? 'service stopped' : null)
    || (forecastFreshness.className === 'is-stale' ? 'forecast artifact stale' : null)
    || 'no blocking condition published';

  let loopHealthScore = 100;
  if (!serviceActive) loopHealthScore -= 35;
  if (snapshotAgeMinutes > freshnessSlaMinutes) loopHealthScore -= 12;
  if (serviceAgeMinutes > freshnessSlaMinutes) loopHealthScore -= 12;
  if (launchBlocked) loopHealthScore -= 24;
  if (verificationFailedCount > 0) loopHealthScore -= 14;
  if (forecastFreshness.className === 'is-stale') loopHealthScore -= 8;
  if (btc5LiveFilledRows <= 0) loopHealthScore -= 10;
  if (velocityFillGrowth <= 0) loopHealthScore -= 7;
  if (btc5WindowPnlUsd < 0) loopHealthScore -= 6;
  loopHealthScore = clamp(loopHealthScore, 0, 100);
  const loopHealth = describeLoopHealth(loopHealthScore);

  const loopLearningState = (() => {
    if (walletClosedPositions <= 0 && btc5LiveFilledRows <= 0) {
      return {
        label: 'no outcome loop',
        tone: 'bad',
        summary: 'Search may be active, but there are no closed positions or live-filled rows feeding the learning side yet.'
      };
    }
    if (velocityFillGrowth > 0 && btc5WindowPnlUsd >= 0 && !launchBlocked) {
      return {
        label: 'compounding',
        tone: 'good',
        summary: `${formatNumber(walletClosedPositions, 0)} closed positions, ${formatNumber(btc5LiveFilledRows, 0)} live-filled rows, and ${formatNumber(velocityFillGrowth, 0)} new validation fills are feeding the next cycle.`
      };
    }
    return {
      label: 'mixed evidence',
      tone: 'warn',
      summary: `${formatNumber(walletClosedPositions, 0)} closed positions and ${formatNumber(btc5LiveFilledRows, 0)} live-filled rows exist, but validation fill growth is flat and sleeve PnL is ${formatUsd(btc5LiveFilledPnlUsd)}.`
    };
  })();

  const loopAttributionState = (() => {
    if (walletClosedPositions >= 20 && launchBlocked) {
      return {
        label: 'partial but blocked',
        tone: 'warn',
        summary: `Sleeve-level attribution exists across ${formatNumber(walletClosedPositions, 0)} closed positions, but fund-level claims stay blocked until reconciliation and launch truth line up.`
      };
    }
    if (walletClosedPositions >= 20) {
      return {
        label: 'strong',
        tone: 'good',
        summary: `Closed-position coverage is deep enough to attribute live behavior to the BTC5 sleeve without leaning on blended fund claims.`
      };
    }
    if (walletClosedPositions > 0) {
      return {
        label: 'thin',
        tone: 'warn',
        summary: `Some attribution exists, but the closed-trade base is still shallow enough that the learning loop can overreact to noise.`
      };
    }
    return {
      label: 'missing',
      tone: 'bad',
      summary: 'No durable attribution surface is available yet, so any perceived gains would be too easy to overstate.'
    };
  })();

  const loopExecutionState = (() => {
    if (!serviceActive) {
      return {
        label: 'offline',
        tone: 'bad',
        summary: 'The runtime is not running, so the loop cannot collect fresh evidence or execution outcomes.'
      };
    }
    if (btc5LiveFilledRows <= 0) {
      return {
        label: 'no live sleeve proof',
        tone: 'bad',
        summary: 'The service is up, but there are no BTC5 live-filled rows on the board yet.'
      };
    }
    if (btc5AgeMinutes > 720) {
      return {
        label: 'quiet sleeve',
        tone: 'warn',
        summary: `${formatNumber(btc5LiveFilledRows, 0)} live-filled rows exist, but the last fill is ${btc5Freshness.label} and the sleeve is not producing fresh execution evidence right now.`
      };
    }
    return {
      label: 'active',
      tone: 'good',
      summary: `${formatNumber(btc5LiveFilledRows, 0)} live-filled rows and a ${btc5Freshness.label} fill cadence show the sleeve is still feeding execution evidence.`
    };
  })();

  const loopStages = {
    search: {
      label: dispatchWorkOrders > 0 || strategyCatalog.pipeline > 0 ? 'running' : 'thin',
      tone: dispatchWorkOrders > 0 || strategyCatalog.pipeline > 0 ? 'good' : 'warn',
      summary: `${formatNumber(strategyCatalog.total, 0)} tracked strategies, ${formatNumber(dispatchWorkOrders, 0)} active work-orders, and ${formatNumber(researchFiles, 0)} dispatch files are feeding the search side of the loop.`
    },
    evidence: {
      label: !serviceActive ? 'down' : freshnessSlaStatus.tone === 'good' ? 'fresh' : freshnessSlaStatus.tone === 'warn' ? 'aging' : 'stale',
      tone: !serviceActive ? 'bad' : freshnessSlaStatus.tone,
      summary: `Snapshot ${snapshotFreshness.label}, service ${serviceFreshness.label}, BTC5 ${btc5Freshness.label}, forecast ${forecastFreshness.label}. Freshness SLA is ${formatNumber(freshnessSlaMinutes, 0)} minutes.`
    },
    gate: {
      label: !launchBlocked && verificationFailedCount === 0 ? 'clear' : launchBlocked ? 'blocked' : 'warning',
      tone: !launchBlocked && verificationFailedCount === 0 ? 'good' : launchBlocked ? 'bad' : 'warn',
      summary: launchBlocked
        ? `Launch is blocked by ${summarizeList(launchReasons, 2)}. Verification currently shows ${verificationFailedCount} failing tests.`
        : verificationFailedCount
          ? `Launch is clear, but ${verificationFailedCount} failing root tests still make promotion unsafe.`
          : 'Harness posture is clear enough that fresh evidence could promote without hidden control-plane drift.'
    },
    execution: {
      label: loopExecutionState.label,
      tone: loopExecutionState.tone,
      summary: `${loopExecutionState.summary} Window proof: ${formatNumber(btc5WindowLiveFills, 0)} fills over ${formatHours(btc5WindowHours)}h with ${formatUsd(btc5WindowPnlUsd)} sleeve PnL.`
    },
    learning: {
      label: loopLearningState.label,
      tone: loopLearningState.tone,
      summary: `${loopLearningState.summary} Attribution is ${loopAttributionState.label}, and the latest forecast window shows ${formatNumber(velocityFillGrowth, 0)} new validation fills across ${formatNumber(velocityCycles, 0)} cycles.`
    }
  };
  loopStages.search.summary = `${formatNumber(strategyCatalog.total, 0)} tracked strategies, ${formatNumber(dispatchWorkOrders, 0)} active work-orders, ${formatNumber(researchFiles, 0)} dispatch files, and ${formatNumber(velocityCycles, 0)} recent forecast cycles keep the upstream search busy. The bottleneck is downstream proof, not idea generation.`;

  const loopHealthSummary = [
    serviceActive ? 'Runtime heartbeat is present.' : 'Runtime heartbeat is absent.',
    launchBlocked ? `Launch remains blocked by ${summarizeList(launchReasons, 2)}.` : 'Launch contract is clear.',
    verificationFailedCount ? `${formatNumber(verificationFailedCount, 0)} root test failures are still open.` : 'Root verification is green.',
    velocityFillGrowth > 0 ? `Validation fill growth is +${formatNumber(velocityFillGrowth, 0)}.` : 'Validation fill growth is flat.'
  ].join(' ');
  const loopParticleCount = clamp(
    Math.round(dispatchWorkOrders / 9) + Math.round(strategyCatalog.deployed / 3) + Math.min(velocityCycles, 5),
    5,
    13
  );
  const loopParticleTones = Array.from({ length: loopParticleCount }, (_, index) => {
    const tones = [
      loopStages.search.tone,
      loopStages.evidence.tone,
      loopStages.gate.tone,
      loopStages.execution.tone,
      loopStages.learning.tone
    ];
    return tones[index % tones.length];
  });
  const trendStart = forecastTrendSeries[0] || null;
  const trendEnd = forecastTrendSeries[forecastTrendSeries.length - 1] || null;
  const loopVisualSummary = `Packets orbiting the ring represent active hypotheses and proof work moving through search, evidence, gate, execution, and learning. Count scales with current work-orders, deployed lanes, and recent forecast cycles.`;
  const loopTrendSummary = forecastTrendSeries.length
    ? `${formatNumber(forecastTrendSeries.length, 0)} checked-in forecast checkpoints span ${formatHours(velocityWindowHours)}h. The active package moved from ${formatCompactPercentOrLabel(trendStart?.active)} to ${formatCompactPercentOrLabel(trendEnd?.active)} while live-fill bars stayed ${Math.max(...forecastTrendSeries.map(point => point.fills), 0) > 0 ? 'thin' : 'flat at zero'} in the public forecast loop.`
    : 'No checked-in forecast trend is published yet.';

  return {
    cycleLabel,
    cycleNumber,
    currentSystemArrPct,
    cyclesCompleted: normalizeNumber(pick(runtime, ['cycles_completed'], pick(detail, ['cycles_completed'], 565)), 565),
    totalTrades: normalizeNumber(pick(runtime, ['total_trades'], pick(detail, ['total_trades'], 5)), 5),
    walletCount: normalizeNumber(pick(pipeline, ['public_safe_counts.wallet_flow.wallet_count'], 80), 80),
    walletReady: true,
    walletStatus: 'ready',
    serviceActive,
    serviceStateLabel,
    serviceCheckedAt,
    serviceDriftNote: serviceActive
      ? 'The broader runtime is running, but public claims still need the launch gates.'
      : 'The broader runtime is stopped while the dedicated BTC5 sleeve remains the public proof surface.',
    serverLocation: DEFAULTS.server.location,
    serverDetail: DEFAULTS.server.detail,
    launchBlocked,
    launchReasonsSummary: summarizeList(launchReasons, 3),
    nextAction: pick(launch, ['next_operator_action'], 'Keep the BTC5 sleeve visible, keep fund-level realized ARR blocked, and close ledger and wallet reconciliation.'),
    fastVerdict: pick(snapshot, ['latest_pipeline.recommendation'], pick(pipelineSummary, ['recommendation'], 'REJECT ALL')),
    fastMarketsObserved: normalizeNumber(fastMarkets.total_markets_observed || pick(pipelineSummary, ['markets_scanned'], 75), 75),
    fastMarkets15m: normalizeNumber(fastMarkets.markets_15m || 29, 29),
    fastMarkets5m: normalizeNumber(fastMarkets.markets_5m || 39, 39),
    fastMarkets4h: normalizeNumber(fastMarkets.markets_4h || 7, 7),
    tradeRecords: normalizeNumber(fastMarkets.trade_records || 3047, 3047),
    uniqueWallets: normalizeNumber(fastMarkets.unique_wallets || 1715, 1715),
    edgeSummary,
    a6AllowedEvents: normalizeNumber(a6Snapshot.allowed_neg_risk_event_count || 563, 563),
    a6QualifiedEvents: normalizeNumber(arbQualified, 57),
    a6Executable: normalizeNumber(a6Snapshot.executable_constructions_below_threshold || 0, 0),
    b1Pairs: normalizeNumber(b1Snapshot.deterministic_template_pair_count || 0, 0),
    b1Sample: normalizeNumber(b1Snapshot.allowed_market_sample_size || 1000, 1000),
    verificationSummary: rootVerificationSummary,
    verificationRootDetail: verificationParsed.failed
      ? `${verificationParsed.failed} failed current root suites`
      : verificationParsed.passedTotal
        ? `${formatNumber(verificationParsed.passedTotal, 0)} passed current root suites`
        : rootVerificationSummary,
    verificationBaselineTotal,
    avgTestsPerDay: normalizeNumber(pick(velocityMetrics, ['avg_tests_per_day'], 57.1), 57.1),
    avgDispatchesPerDay: normalizeNumber(pick(velocityMetrics, ['avg_dispatches_per_day'], 4.3), 4.3),
    velocitySpanDays: normalizeNumber(pick(velocityMetrics, ['project_age_days'], pick(velocity, ['velocity_summary.timeline_span_days'], 22)), 22),
    strategyCatalog,
    dispatchWorkOrders,
    researchFiles,
    benchmarkedSystems,
    primarySignalLanes: DEFAULTS.primarySignalLanes,
    anomalySignalLanes: DEFAULTS.anomalySignalLanes,
    commitCount,
    calibratedWinRate: DEFAULTS.calibratedWinRate,
    legacyWinRate: DEFAULTS.legacyWinRate,
    noOnlyWinRate: DEFAULTS.noOnlyWinRate,
    risk: DEFAULTS.risk,
    diaryEntries: DEFAULTS.diaryEntries,
    generatedAt,
    runtimeSplitSummary: btc5LiveFilledRows > 0
      ? `jj-live ${serviceStateLabel} / BTC5 live / fund claim ${humanizeClaimStatus(pick(scoreboard, ['fund_realized_arr_claim_status'], 'blocked')).toLowerCase()}`
      : `jj-live ${serviceStateLabel} / launch ${launchBlocked ? 'blocked' : 'clear'}`,
    headlineSummary: pick(
      headline,
      ['summary'],
      `BTC5 live sleeve has ${formatNumber(btc5LiveFilledRows, 0)} live-filled rows and ${formatUsd(btc5LiveFilledPnlUsd)} live-filled PnL. Fund-level realized ARR stays blocked.`
    ),
    fundClaimStatusLabel: humanizeClaimStatus(pick(scoreboard, ['fund_realized_arr_claim_status'], 'blocked')),
    fundClaimReason,
    fundClaimReasonShort: shorten(fundClaimReason, 132),
    btc5LiveFilledPnlUsd,
    btc5LiveFilledRows,
    btc5LatestFillAt,
    btc5SourceLabel: humanizeSource(pick(maker, ['source'], pick(runtime, ['btc5_source'], 'remote_sqlite_probe'))),
    btc5DbPath: pick(maker, ['db_path'], pick(runtime, ['btc5_db_path'], 'reports/tmp_remote_btc_5min_maker.db')),
    btc5BestBucket: bestPriceBucket,
    btc5BestBucketPnlUsd: bestPriceBucketPnlUsd,
    btc5BestDirection: bestDirection,
    btc5BestDirectionPnlUsd: bestDirectionPnlUsd,
    btc5Guardrails: `max_abs_delta=${pick(guardrail, ['max_abs_delta'], 0.00015)} / UP<=${pick(guardrail, ['up_max_buy_price'], 0.51)} / DOWN<=${pick(guardrail, ['down_max_buy_price'], 0.51)}`,
    btc5LatestOrderStatus: pick(maker, ['latest_trade.order_status'], pick(runtime, ['btc5_latest_order_status'], 'skip_price_outside_guardrails')),
    btc5RunRateCompact: formatCompactPercentOrLabel(pick(scoreboard, ['realized_btc5_sleeve_run_rate_pct'], null)),
    btc5RunRateExact: formatPercentOrLabel(pick(scoreboard, ['realized_btc5_sleeve_run_rate_pct'], null)),
    btc5WindowPnlUsd,
    btc5WindowHours,
    btc5WindowLiveFills,
    forecastArrCompact: formatCompactPercentOrLabel(forecastArrPct),
    forecastArrExact: formatPercentOrLabel(forecastArrPct),
    forecastBestArrCompact: formatCompactPercentOrLabel(forecastBestArrPct),
    forecastDeltaCompact: formatCompactPercentOrLabel(forecastDeltaPct),
    forecastDeltaExact: formatPercentOrLabel(forecastDeltaPct),
    forecastConfidenceLabel: titleCase(pick(scoreboard, ['forecast_confidence_label'], pick(confidence, ['label'], 'high'))),
    forecastConfidenceReasons: (pick(scoreboard, ['forecast_confidence_reasons'], pick(confidence, ['reasons'], [])) || []).join('; '),
    forecastSourcePath,
    deployRecommendationLabel: titleCase(pick(scoreboard, ['deploy_recommendation'], 'promote')),
    velocityWindowHours,
    velocityCycles,
    velocityGainCompact: formatCompactPercentOrLabel(velocityGainPct),
    velocityGainExact: formatPercentOrLabel(velocityGainPct),
    velocityPerDayCompact: formatCompactPercentOrLabel(velocityPerDayPct),
    velocityFillGrowth: normalizeNumber(pick(timeboundVelocity, ['validation_fill_growth'], 0), 0),
    velocityConfidenceLabel: titleCase(pick(timeboundVelocity, ['confidence_label'], pick(scoreboard, ['forecast_confidence_label'], 'high'))),
    loopHealthScore,
    loopHealthTone: loopHealth.tone,
    loopHealthLabel: loopHealth.label,
    loopHealthTag: `${formatNumber(loopHealthScore, 0)}/100`,
    loopHealthSummary,
    loopFreshnessStatus: freshnessSlaStatus.label,
    loopStalenessSummary: `snapshot ${snapshotFreshness.label}; BTC5 ${btc5Freshness.label}; forecast ${forecastFreshness.label}; tests ${buildFreshness(pick(rootTestStatus, ['checked_at'], generatedAt)).label}`,
    loopPrimaryBlocker: titleCase(primaryBlocker),
    loopOperatorAction: shorten(pick(launch, ['next_operator_action'], 'Keep the proof surface current and repair the launch contract before trusting new gains.'), 132),
    loopLearningStatus: titleCase(loopLearningState.label),
    loopLearningSummary: loopLearningState.summary,
    loopAttributionStatus: titleCase(loopAttributionState.label),
    loopAttributionSummary: loopAttributionState.summary,
    loopSearchSummary: loopStages.search.summary,
    loopExecutionStatus: titleCase(loopExecutionState.label),
    loopExecutionSummary: loopExecutionState.summary,
    loopVisualPackets: `${formatNumber(loopParticleCount, 0)} packets`,
    loopVisualSummary,
    loopCoreNote: `${titleCase(loopStages.search.label)} search / ${titleCase(loopStages.gate.label)} gate / ${titleCase(loopStages.learning.label)} learning`,
    loopTrendSummary,
    loopTrendStartLabel: trendStart ? formatShortUtc(trendStart.timestamp) : 'no start',
    loopTrendEndLabel: trendEnd ? formatShortUtc(trendEnd.timestamp) : 'no end',
    loopTrendSeries: forecastTrendSeries,
    loopParticleTones,
    loopStages,
    walletOpenPositions: normalizeNumber(pick(runtime, ['polymarket_open_positions'], pick(wallet, ['open_positions_count'], 0)), 0),
    walletClosedPositions,
    walletRealizedPnlUsd: normalizeNumber(
      pick(runtime, ['polymarket_closed_positions_realized_pnl_usd'], pick(wallet, ['closed_positions_realized_pnl_usd'], 0)),
      0
    ),
    jjnPhase: pick(jjn, ['phase'], 'Phase 0 launch prep'),
    jjnCurrentPhaseLabel: titleCase(pick(jjnActivation, ['current_phase'], 'instrumentation_and_approval')),
    jjnClaimStatusLabel: humanizeClaimStatus(pick(jjn, ['claim_status'], 'prelaunch')),
    jjnClaimReason: pick(jjn, ['claim_reason'], 'The worker surface is still launch prep.'),
    jjnOfferName,
    jjnOfferPrice: pick(jjnOffer, ['price_range_usd'], '$500-$2,500'),
    jjnOfferDeliveryDays: normalizeNumber(pick(jjnOffer, ['delivery_days'], 5), 5),
    jjnOfferStatusLabel: titleCase(pick(jjnOffer, ['status'], 'implemented_in_code_not_launched')),
    jjnApprovalModeLabel: titleCase(pick(jjnActivation, ['approval_mode'], 'human_review_required')),
    jjnSendStatusLabel: titleCase(pick(jjnActivation, ['send_status'], 'blocked_pending_verified_domain_and_explicit_approval')),
    jjnFulfillmentStatusLabel: titleCase(pick(jjnActivation, ['fulfillment_status'], 'placeholders_defined_not_launched')),
    jjnEnginesFunctional: normalizeNumber(pick(jjnEvidence, ['engines_functional'], 5), 5),
    jjnTemplatesCount: normalizeNumber(pick(jjnEvidence, ['templates_count'], 3), 3),
    jjnDashboardCount: normalizeNumber(pick(jjnEvidence, ['dashboard_count'], 1), 1),
    jjnPackageTests: normalizeNumber(pick(jjnEvidence, ['package_tests_passed'], 61), 61),
    jjnRepoTests: normalizeNumber(pick(jjnEvidence, ['repo_tests_passed'], 49), 49),
    jjnAccountsResearched: normalizeNumber(pick(jjnFunnel, ['accounts_researched'], 0), 0),
    jjnQualifiedAccounts: normalizeNumber(pick(jjnFunnel, ['qualified_accounts'], 0), 0),
    jjnOutreachApproved: normalizeNumber(pick(jjnFunnel, ['outreach_approved'], 0), 0),
    jjnMessagesDelivered: normalizeNumber(pick(jjnFunnel, ['messages_delivered'], 0), 0),
    jjnReplies: normalizeNumber(pick(jjnFunnel, ['replies'], 0), 0),
    jjnMeetingsBooked: normalizeNumber(pick(jjnFunnel, ['meetings_booked'], 0), 0),
    jjnProposalsSent: normalizeNumber(pick(jjnFunnel, ['proposals_sent'], 0), 0),
    jjnOutcomesRecorded: normalizeNumber(pick(jjnFunnel, ['outcomes_recorded'], 0), 0),
    jjnRevenueWonUsd: normalizeNumber(pick(jjnFunnel, ['revenue_won_usd'], 0), 0),
    jjnGrossMarginUsd: normalizeNumber(pick(jjnFunnel, ['gross_margin_usd'], 0), 0),
    jjnTimeToFirstDollar: pick(jjnFunnel, ['time_to_first_dollar_days'], null) === null
      ? 'not started'
      : `${formatNumber(pick(jjnFunnel, ['time_to_first_dollar_days'], 0), 1)} days`,
    jjnReplyRate: pick(jjn, ['conversion.reply_rate_pct'], null) === null
      ? 'not published'
      : formatPercent(pick(jjn, ['conversion.reply_rate_pct'], 0)),
    jjnBlockersShort: summarizeList(pick(jjn, ['blockers'], []), 2),
    snapshotSource: pick(snapshot, ['snapshot_source'], 'reports/runtime_truth_latest.json'),
    elasticSharedSubstrateSummary,
    elasticWorkerFamilyCoverage,
    elasticArtifactBackedProof,
    elasticOperatorSurfaceSummary,
    elasticPublishLoopSummary,
    elasticPublicScopeGuardrail,
    elasticEmployeePathLive,
    elasticEmployeePathRepo,
    elasticEmployeePathDevelop,
    elasticEmployeePathContribute,
    elasticEmployeePathSummary: [
      elasticEmployeePathLive,
      elasticEmployeePathRepo,
      elasticEmployeePathDevelop,
      elasticEmployeePathContribute
    ].join(' / '),
    snapshotFreshness,
    btc5Freshness,
    forecastFreshness,
    jjnFreshness
  };
}

async function initSite() {
  setActiveNav();
  const data = await loadSiteData();
  setCommonValues(data);
  setStatusPill(data);
  applyLiveEnhancements(data);
  applyElasticEnhancements(data);
}

document.addEventListener('DOMContentLoaded', () => {
  initSite().catch(() => {
    setActiveNav();
  });
});
