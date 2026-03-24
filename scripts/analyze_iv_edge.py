#!/usr/bin/env python3
"""Offline correlation analysis: does Deribit IV data predict BTC5 candle outcomes?

Run weekly or after 500+ IV-enriched rows accumulate. Computes 6 correlation
families (skew vs direction, DVOL regime, DVOL change, risk reversal, IV vs
spread, composite signal) with statistical significance tests.

KILL RULE: If after 1000 IV-enriched rows, NO correlation passes p < 0.10
with edge > 1%, the IV feed adds no value and should be removed.

Usage:
    python3 scripts/analyze_iv_edge.py --db-path data/btc_5min_maker.db
    python3 scripts/analyze_iv_edge.py --db-path /path/to/remote_copy.db --min-samples 30
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIVE_FILLED_STATUSES = {
    "live_filled",
    "live_partial_fill_cancelled",
    "live_partial_fill_open",
}

IV_COLUMNS = [
    "deribit_dvol",
    "deribit_atm_iv_call",
    "deribit_atm_iv_put",
    "deribit_put_call_skew",
    "deribit_rr_25d",
    "deribit_bf_25d",
    "deribit_underlying",
    "deribit_age_s",
]

DEFAULT_DB = ROOT / "data" / "btc_5min_maker.db"
DEFAULT_MIN_SAMPLES = 50
REPORT_DIR = ROOT / "reports"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CorrelationResult:
    name: str
    description: str
    n_total: int = 0
    n_group_a: int = 0
    n_group_b: int = 0
    wr_group_a: float = 0.0
    wr_group_b: float = 0.0
    edge_pct: float = 0.0
    ci_low_a: float = 0.0
    ci_high_a: float = 0.0
    ci_low_b: float = 0.0
    ci_high_b: float = 0.0
    p_value: float = 1.0
    test_used: str = ""
    actionable: bool = False
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 6)
        return d


@dataclass
class AnalysisReport:
    timestamp: str = ""
    db_path: str = ""
    total_rows: int = 0
    iv_enriched_rows: int = 0
    resolved_rows: int = 0
    iv_and_resolved_rows: int = 0
    min_samples: int = DEFAULT_MIN_SAMPLES
    correlations: list[CorrelationResult] = field(default_factory=list)
    actionable_count: int = 0
    kill_rule_status: str = ""
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["correlations"] = [c.to_dict() for c in self.correlations]
        return d


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p_hat = wins / n
    denom = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * n)) / n) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def chi_squared_2x2(a: int, b: int, c: int, d: int) -> float:
    """Chi-squared test for a 2x2 contingency table. Returns p-value.

    Table layout:
        | win  | loss |
    A   |  a   |  b   |
    B   |  c   |  d   |
    """
    n = a + b + c + d
    if n == 0:
        return 1.0
    # Expected values
    r1 = a + b
    r2 = c + d
    c1 = a + c
    c2 = b + d
    expected = [
        (r1 * c1 / n, r1 * c2 / n),
        (r2 * c1 / n, r2 * c2 / n),
    ]
    # Any expected cell < 5 => use Fisher exact (approximate via chi-sq with
    # Yates correction)
    use_yates = any(e < 5 for row in expected for e in row)
    chi2 = 0.0
    for observed, exp_row in zip([(a, b), (c, d)], expected):
        for obs, exp in zip(observed, exp_row):
            if exp == 0:
                continue
            diff = abs(obs - exp) - (0.5 if use_yates else 0)
            chi2 += (diff * diff) / exp
    # p-value from chi-squared distribution with 1 df
    # Using survival function approximation (no scipy dependency)
    p = _chi2_sf(chi2, df=1)
    return p


def _chi2_sf(x: float, df: int = 1) -> float:
    """Survival function for chi-squared distribution (1 df).

    Uses the complementary error function relationship:
    P(chi2 > x | df=1) = erfc(sqrt(x/2))
    """
    if x <= 0:
        return 1.0
    if df == 1:
        return math.erfc(math.sqrt(x / 2))
    # For df > 1, use regularized incomplete gamma approximation
    # (not needed for 2x2 tables but included for safety)
    return _regularized_gamma_q(df / 2.0, x / 2.0)


def _regularized_gamma_q(a: float, x: float) -> float:
    """Upper regularized incomplete gamma function Q(a, x) via series."""
    if x < 0:
        return 1.0
    if x == 0:
        return 1.0
    # Use continued fraction for Q when x >= a + 1
    if x >= a + 1:
        return _gamma_cf(a, x)
    # Otherwise Q = 1 - P where P uses series
    return 1.0 - _gamma_series(a, x)


def _gamma_series(a: float, x: float, max_iter: int = 200) -> float:
    """Lower regularized gamma P(a,x) via series expansion."""
    if x == 0:
        return 0.0
    ap = a
    s = 1.0 / a
    ds = s
    for _ in range(max_iter):
        ap += 1
        ds *= x / ap
        s += ds
        if abs(ds) < abs(s) * 1e-12:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_cf(a: float, x: float, max_iter: int = 200) -> float:
    """Upper regularized gamma Q(a,x) via continued fraction."""
    b = x + 1 - a
    c = 1e30
    d = 1 / b if b != 0 else 1e30
    h = d
    for i in range(1, max_iter + 1):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Fisher exact test p-value for 2x2 table (two-sided).

    Falls back to chi-squared for large tables (n > 300) to avoid
    numerical overflow in factorial computation.
    """
    n = a + b + c + d
    if n > 300:
        return chi_squared_2x2(a, b, c, d)
    # Hypergeometric probability
    r1, r2, c1, c2 = a + b, c + d, a + c, b + d
    p_cutoff = _hypergeom_pmf(a, n, r1, c1)
    p_value = 0.0
    for x in range(min(r1, c1) + 1):
        p = _hypergeom_pmf(x, n, r1, c1)
        if p <= p_cutoff + 1e-12:
            p_value += p
    return min(1.0, p_value)


def _hypergeom_pmf(k: int, N: int, K: int, n: int) -> float:
    """Hypergeometric PMF using log-factorials."""
    if k < max(0, n + K - N) or k > min(n, K):
        return 0.0
    log_p = (
        _log_comb(K, k)
        + _log_comb(N - K, n - k)
        - _log_comb(N, n)
    )
    return math.exp(log_p)


def _log_comb(n: int, k: int) -> float:
    """Log of binomial coefficient C(n, k)."""
    if k < 0 or k > n:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _has_iv_columns(conn: sqlite3.Connection) -> bool:
    """Check if the IV columns exist in window_trades."""
    cursor = conn.execute("PRAGMA table_info(window_trades)")
    cols = {row[1] for row in cursor.fetchall()}
    return "deribit_dvol" in cols


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def load_rows(
    db_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load rows from the BTC5 database.

    Returns:
        (all_rows, iv_rows, resolved_iv_rows)
        - all_rows: every row in window_trades
        - iv_rows: rows where deribit_dvol IS NOT NULL
        - resolved_iv_rows: iv_rows where won IS NOT NULL
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    has_iv = _has_iv_columns(conn)

    iv_select = ", ".join(IV_COLUMNS) if has_iv else ""
    iv_clause = f", {iv_select}" if iv_select else ""

    query = f"""
        SELECT direction, delta, order_status, won, pnl_usd,
               created_at, best_bid, best_ask, order_price,
               trade_size_usd{iv_clause}
        FROM window_trades
        ORDER BY created_at
    """
    rows = [dict(r) for r in conn.execute(query).fetchall()]
    conn.close()

    if not has_iv:
        return rows, [], []

    iv_rows = [r for r in rows if r.get("deribit_dvol") is not None]
    resolved_iv = [r for r in iv_rows if r.get("won") is not None]
    return rows, iv_rows, resolved_iv


# ---------------------------------------------------------------------------
# Correlation computations
# ---------------------------------------------------------------------------


def _split_and_compute(
    rows: list[dict[str, Any]],
    name: str,
    description: str,
    split_fn: Any,
    min_samples: int,
) -> CorrelationResult:
    """Split rows into two groups by split_fn, compute WR and significance.

    split_fn(row) -> True for group A, False for group B, None to exclude.
    Group A is the "signal present" group; edge = WR_A - WR_B.
    """
    group_a_wins, group_a_total = 0, 0
    group_b_wins, group_b_total = 0, 0

    for r in rows:
        if r.get("won") is None:
            continue
        bucket = split_fn(r)
        if bucket is None:
            continue
        won = int(r["won"])
        if bucket:
            group_a_total += 1
            group_a_wins += won
        else:
            group_b_total += 1
            group_b_wins += won

    wr_a = group_a_wins / group_a_total if group_a_total > 0 else 0.0
    wr_b = group_b_wins / group_b_total if group_b_total > 0 else 0.0
    edge = (wr_a - wr_b) * 100  # percentage points

    ci_a = wilson_ci(group_a_wins, group_a_total)
    ci_b = wilson_ci(group_b_wins, group_b_total)

    # Significance test
    if group_a_total + group_b_total < 20:
        p = 1.0
        test = "insufficient_data"
    elif min(group_a_total, group_b_total) < 5:
        p = fisher_exact_2x2(
            group_a_wins,
            group_a_total - group_a_wins,
            group_b_wins,
            group_b_total - group_b_wins,
        )
        test = "fisher_exact"
    else:
        p = chi_squared_2x2(
            group_a_wins,
            group_a_total - group_a_wins,
            group_b_wins,
            group_b_total - group_b_wins,
        )
        test = "chi_squared_yates" if min(group_a_total, group_b_total) < 30 else "chi_squared"

    actionable = (
        group_a_total >= min_samples
        and group_b_total >= min_samples
        and p < 0.05
        and abs(edge) > 2.0
    )

    reason = ""
    if group_a_total < min_samples or group_b_total < min_samples:
        reason = f"insufficient samples (A={group_a_total}, B={group_b_total}, need {min_samples})"
    elif p >= 0.05:
        reason = f"not significant (p={p:.4f})"
    elif abs(edge) <= 2.0:
        reason = f"edge too small ({edge:+.2f}%)"

    return CorrelationResult(
        name=name,
        description=description,
        n_total=group_a_total + group_b_total,
        n_group_a=group_a_total,
        n_group_b=group_b_total,
        wr_group_a=wr_a,
        wr_group_b=wr_b,
        edge_pct=edge,
        ci_low_a=ci_a[0],
        ci_high_a=ci_a[1],
        ci_low_b=ci_b[0],
        ci_high_b=ci_b[1],
        p_value=p,
        test_used=test,
        actionable=actionable,
        reason=reason,
    )


def corr_a_skew_vs_direction(
    rows: list[dict[str, Any]], min_samples: int
) -> list[CorrelationResult]:
    """A. SKEW vs DIRECTION: Does put_call_skew predict DOWN wins?"""
    results = []
    down_rows = [r for r in rows if r.get("direction") == "DOWN"]

    for threshold in [-2, -1, 0, 1, 2, 3, 5]:
        def split(r: dict, t: int = threshold) -> bool | None:
            skew = r.get("deribit_put_call_skew")
            if skew is None:
                return None
            return float(skew) > t

        result = _split_and_compute(
            down_rows,
            f"skew_gt_{threshold}_down_wr",
            f"P(DOWN wins | skew > {threshold}) vs P(DOWN wins | skew <= {threshold})",
            split,
            min_samples,
        )
        results.append(result)
    return results


def corr_b_dvol_regime(
    rows: list[dict[str, Any]], min_samples: int
) -> list[CorrelationResult]:
    """B. DVOL REGIME: High vs low DVOL win rates by side."""
    results = []
    for side in ["DOWN", "UP"]:
        side_rows = [r for r in rows if r.get("direction") == side]

        def split_high(r: dict) -> bool | None:
            dvol = r.get("deribit_dvol")
            if dvol is None:
                return None
            return float(dvol) > 60

        result = _split_and_compute(
            side_rows,
            f"dvol_high_vs_low_{side.lower()}",
            f"WR({side} | DVOL > 60) vs WR({side} | DVOL <= 60)",
            split_high,
            min_samples,
        )
        results.append(result)

    # Also test DVOL < 50 vs >= 50 boundary
    for side in ["DOWN", "UP"]:
        side_rows = [r for r in rows if r.get("direction") == side]

        def split_50(r: dict) -> bool | None:
            dvol = r.get("deribit_dvol")
            if dvol is None:
                return None
            return float(dvol) >= 50

        result = _split_and_compute(
            side_rows,
            f"dvol_ge50_vs_lt50_{side.lower()}",
            f"WR({side} | DVOL >= 50) vs WR({side} | DVOL < 50)",
            split_50,
            min_samples,
        )
        results.append(result)
    return results


def corr_c_dvol_change(
    rows: list[dict[str, Any]], min_samples: int
) -> list[CorrelationResult]:
    """C. DVOL CHANGE: Does rising DVOL predict direction?"""
    # Compute dvol_delta for consecutive rows
    enriched = []
    prev_dvol = None
    for r in rows:
        dvol = r.get("deribit_dvol")
        if dvol is not None and prev_dvol is not None:
            r_copy = dict(r)
            r_copy["dvol_delta"] = float(dvol) - float(prev_dvol)
            enriched.append(r_copy)
        if dvol is not None:
            prev_dvol = float(dvol)

    results = []
    buckets = [
        ("dvol_falling_fast", "dvol_delta < -2", lambda d: d < -2),
        ("dvol_falling_slow", "-2 <= dvol_delta < 0", lambda d: -2 <= d < 0),
        ("dvol_rising_slow", "0 <= dvol_delta < 2", lambda d: 0 <= d < 2),
        ("dvol_rising_fast", "dvol_delta >= 2", lambda d: d >= 2),
    ]

    for side in ["DOWN", "UP"]:
        side_enriched = [r for r in enriched if r.get("direction") == side]
        for bname, bdesc, bfn in buckets:
            def split(r: dict, fn: Any = bfn) -> bool | None:
                dd = r.get("dvol_delta")
                if dd is None:
                    return None
                return fn(dd)

            result = _split_and_compute(
                side_enriched,
                f"{bname}_{side.lower()}",
                f"WR({side} | {bdesc}) vs WR({side} | not)",
                split,
                min_samples,
            )
            results.append(result)
    return results


def corr_d_risk_reversal(
    rows: list[dict[str, Any]], min_samples: int
) -> list[CorrelationResult]:
    """D. RISK REVERSAL: Does rr_25d sign predict candle direction?"""
    results = []
    down_rows = [r for r in rows if r.get("direction") == "DOWN"]

    # rr_25d > 1 means puts richer than calls (fear of downside)
    def split_rr_pos(r: dict) -> bool | None:
        rr = r.get("deribit_rr_25d")
        if rr is None:
            return None
        return float(rr) > 1

    results.append(
        _split_and_compute(
            down_rows,
            "rr25d_gt1_down_wr",
            "P(DOWN wins | rr_25d > 1) vs P(DOWN wins | rr_25d <= 1)",
            split_rr_pos,
            min_samples,
        )
    )

    # Also test rr_25d < -1 predicting UP wins
    up_rows = [r for r in rows if r.get("direction") == "UP"]

    def split_rr_neg(r: dict) -> bool | None:
        rr = r.get("deribit_rr_25d")
        if rr is None:
            return None
        return float(rr) < -1

    results.append(
        _split_and_compute(
            up_rows,
            "rr25d_lt_neg1_up_wr",
            "P(UP wins | rr_25d < -1) vs P(UP wins | rr_25d >= -1)",
            split_rr_neg,
            min_samples,
        )
    )
    return results


def corr_e_iv_vs_spread(
    rows: list[dict[str, Any]], _min_samples: int
) -> CorrelationResult:
    """E. IV vs SPREAD: Does higher DVOL correlate with wider spreads?"""
    # Compute spread for each row
    pairs = []
    for r in rows:
        dvol = r.get("deribit_dvol")
        bid = r.get("best_bid")
        ask = r.get("best_ask")
        if dvol is None or bid is None or ask is None:
            continue
        spread = _safe_float(ask) - _safe_float(bid)
        if spread < 0:
            continue
        pairs.append((_safe_float(dvol), spread))

    if len(pairs) < 10:
        return CorrelationResult(
            name="dvol_vs_spread",
            description="Correlation between DVOL level and CLOB bid-ask spread",
            reason=f"insufficient data ({len(pairs)} pairs)",
        )

    # Bucket DVOL into quintiles
    pairs.sort(key=lambda x: x[0])
    q_size = len(pairs) // 5 or 1
    quintiles: list[dict[str, Any]] = []
    for i in range(5):
        start = i * q_size
        end = start + q_size if i < 4 else len(pairs)
        bucket = pairs[start:end]
        if not bucket:
            continue
        avg_dvol = sum(p[0] for p in bucket) / len(bucket)
        avg_spread = sum(p[1] for p in bucket) / len(bucket)
        quintiles.append({
            "quintile": i + 1,
            "n": len(bucket),
            "avg_dvol": round(avg_dvol, 2),
            "avg_spread": round(avg_spread, 6),
        })

    # Simple rank correlation (Spearman-like): do quintile ranks match?
    # If Q5 spread > Q1 spread, positive correlation
    if len(quintiles) >= 2:
        spread_trend = quintiles[-1]["avg_spread"] - quintiles[0]["avg_spread"]
    else:
        spread_trend = 0.0

    return CorrelationResult(
        name="dvol_vs_spread",
        description="Correlation between DVOL level and CLOB bid-ask spread",
        n_total=len(pairs),
        edge_pct=spread_trend * 10000,  # in basis points
        reason="descriptive only, no significance test",
        detail={"quintiles": quintiles, "spread_trend_raw": round(spread_trend, 6)},
    )


def corr_f_composite_signal(
    rows: list[dict[str, Any]], min_samples: int
) -> CorrelationResult:
    """F. COMPOSITE SIGNAL: Combined skew + risk reversal predicts DOWN?"""
    down_rows = [r for r in rows if r.get("direction") == "DOWN"]

    def compute_composite(r: dict) -> float | None:
        skew = r.get("deribit_put_call_skew")
        rr = r.get("deribit_rr_25d")
        if skew is None or rr is None:
            return None
        s = float(skew)
        rr_val = float(rr)
        # Clamp components to avoid outlier dominance
        skew_component = math.copysign(min(abs(s), 5), s)
        rr_component = math.copysign(min(abs(rr_val), 3), rr_val)
        return skew_component + rr_component

    def split(r: dict) -> bool | None:
        sig = compute_composite(r)
        if sig is None:
            return None
        return sig > 2

    return _split_and_compute(
        down_rows,
        "composite_iv_signal_gt2_down_wr",
        "P(DOWN wins | composite > 2) vs P(DOWN wins | composite <= 2)",
        split,
        min_samples,
    )


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_markdown(report: AnalysisReport) -> str:
    """Render the analysis report as Markdown."""
    lines = [
        "# IV Correlation Analysis Report",
        "",
        f"**Generated:** {report.timestamp}",
        f"**Database:** `{report.db_path}`",
        f"**Min samples per group:** {report.min_samples}",
        "",
        "## Data Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total rows | {report.total_rows} |",
        f"| IV-enriched rows | {report.iv_enriched_rows} |",
        f"| Resolved rows (won/lost known) | {report.resolved_rows} |",
        f"| IV-enriched AND resolved | {report.iv_and_resolved_rows} |",
        "",
    ]

    if report.iv_enriched_rows == 0:
        lines.extend([
            "## Result: No IV Data Available",
            "",
            "Zero IV-enriched rows found. The Deribit IV feed has not yet been",
            "wired into BTC5 decision logging, or no data has accumulated.",
            "Re-run after the IV feed has been active for at least 24 hours.",
            "",
        ])
        return "\n".join(lines)

    if report.iv_and_resolved_rows == 0:
        lines.extend([
            "## Result: IV Data Present But No Resolved Outcomes",
            "",
            f"{report.iv_enriched_rows} IV-enriched rows exist but none have",
            "resolved outcomes yet. Need fills to resolve before correlation",
            "analysis is meaningful. Re-run after trades start resolving.",
            "",
        ])
        return "\n".join(lines)

    # Summary table
    lines.extend([
        "## Correlation Results",
        "",
        "| # | Name | N(A) | N(B) | WR(A) | WR(B) | Edge | p-value | Actionable |",
        "|---|------|------|------|-------|-------|------|---------|------------|",
    ])

    for i, c in enumerate(report.correlations, 1):
        flag = "YES" if c.actionable else "no"
        lines.append(
            f"| {i} | {c.name} | {c.n_group_a} | {c.n_group_b} | "
            f"{c.wr_group_a:.1%} | {c.wr_group_b:.1%} | "
            f"{c.edge_pct:+.2f}% | {c.p_value:.4f} | {flag} |"
        )

    lines.append("")

    # Detail sections for each correlation
    for c in report.correlations:
        lines.extend([
            f"### {c.name}",
            "",
            f"**Description:** {c.description}",
            f"**Test:** {c.test_used} | **p:** {c.p_value:.4f}",
            f"**Group A:** N={c.n_group_a}, WR={c.wr_group_a:.1%} "
            f"[{c.ci_low_a:.1%}, {c.ci_high_a:.1%}]",
            f"**Group B:** N={c.n_group_b}, WR={c.wr_group_b:.1%} "
            f"[{c.ci_low_b:.1%}, {c.ci_high_b:.1%}]",
            f"**Edge:** {c.edge_pct:+.2f} pct pts",
        ])
        if c.actionable:
            lines.append("**Status: ACTIONABLE**")
        elif c.reason:
            lines.append(f"**Status:** {c.reason}")
        if c.detail:
            lines.append(f"**Detail:** ```{json.dumps(c.detail, indent=2)}```")
        lines.append("")

    # Kill rule
    lines.extend([
        "## Kill Rule Assessment",
        "",
        f"**Status:** {report.kill_rule_status}",
        "",
    ])

    # Recommendations
    if report.recommendations:
        lines.extend(["## Recommendations", ""])
        for rec in report.recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def run_analysis(db_path: Path, min_samples: int) -> AnalysisReport:
    """Run the full IV correlation analysis."""
    report = AnalysisReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        db_path=str(db_path),
        min_samples=min_samples,
    )

    if not db_path.exists():
        report.kill_rule_status = f"DB not found at {db_path}"
        return report

    all_rows, iv_rows, resolved_iv = load_rows(db_path)
    report.total_rows = len(all_rows)
    report.iv_enriched_rows = len(iv_rows)

    # Count resolved rows (any row with won != NULL)
    resolved_all = [r for r in all_rows if r.get("won") is not None]
    report.resolved_rows = len(resolved_all)
    report.iv_and_resolved_rows = len(resolved_iv)

    if len(iv_rows) == 0:
        report.kill_rule_status = "NO_DATA: 0 IV-enriched rows"
        report.recommendations.append(
            "Wire Deribit IV feed into BTC5 decision logging and accumulate data."
        )
        return report

    if len(resolved_iv) == 0:
        report.kill_rule_status = "WAITING: IV data exists but no resolved outcomes"
        report.recommendations.append(
            "Wait for BTC5 trades to resolve before running correlation analysis."
        )
        return report

    # Run all 6 correlation families
    correlations: list[CorrelationResult] = []

    # A: Skew vs direction
    correlations.extend(corr_a_skew_vs_direction(resolved_iv, min_samples))

    # B: DVOL regime
    correlations.extend(corr_b_dvol_regime(resolved_iv, min_samples))

    # C: DVOL change
    correlations.extend(corr_c_dvol_change(resolved_iv, min_samples))

    # D: Risk reversal
    correlations.extend(corr_d_risk_reversal(resolved_iv, min_samples))

    # E: IV vs spread (uses all IV rows, not just resolved)
    correlations.append(corr_e_iv_vs_spread(iv_rows, min_samples))

    # F: Composite signal
    correlations.append(corr_f_composite_signal(resolved_iv, min_samples))

    report.correlations = correlations
    report.actionable_count = sum(1 for c in correlations if c.actionable)

    # Kill rule assessment
    if len(resolved_iv) >= 1000:
        # Check if ANY correlation passes p < 0.10 with edge > 1%
        any_promising = any(
            c.p_value < 0.10 and abs(c.edge_pct) > 1.0
            for c in correlations
            if c.n_group_a >= 20 and c.n_group_b >= 20
        )
        if any_promising:
            report.kill_rule_status = "ALIVE: at least one correlation shows promise at N=1000+"
        else:
            report.kill_rule_status = (
                "KILL: 1000+ IV rows, no correlation passes p<0.10 with edge>1%. "
                "IV feed adds no value. Remove to reduce complexity."
            )
            report.recommendations.append(
                "KILL the Deribit IV feed: no predictive signal detected after 1000+ rows."
            )
    elif len(resolved_iv) >= 500:
        any_hint = any(
            c.p_value < 0.20 and abs(c.edge_pct) > 1.0
            for c in correlations
            if c.n_group_a >= 10 and c.n_group_b >= 10
        )
        if any_hint:
            report.kill_rule_status = "PROMISING: signals detected at N=500+, continue to 1000"
        else:
            report.kill_rule_status = "WEAK: 500+ rows, no strong signals yet. Continue to 1000."
    else:
        report.kill_rule_status = (
            f"COLLECTING: {len(resolved_iv)} IV-resolved rows. "
            f"Need 500+ for preliminary, 1000 for kill decision."
        )

    # Generate recommendations
    if report.actionable_count > 0:
        report.recommendations.append(
            f"{report.actionable_count} actionable correlation(s) found. "
            "Review detail sections and consider promoting to live filter."
        )
    else:
        report.recommendations.append(
            "No actionable correlations yet. Continue data collection."
        )

    # Specific recommendations based on data volume
    if len(resolved_iv) < 100:
        report.recommendations.append(
            f"Only {len(resolved_iv)} resolved IV rows. Need 100+ for meaningful analysis."
        )

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Deribit IV correlation with BTC5 candle outcomes"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB,
        help=f"Path to BTC5 SQLite database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"Minimum samples per group for actionable flag (default: {DEFAULT_MIN_SAMPLES})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for reports (default: reports/)",
    )
    args = parser.parse_args()

    report = run_analysis(args.db_path, args.min_samples)

    # Print to stdout
    md = render_markdown(report)
    print(md)

    # Write report files
    out_dir = args.output_dir or REPORT_DIR
    iv_dir = out_dir / "iv_correlation"
    iv_dir.mkdir(parents=True, exist_ok=True)

    datestamp = datetime.now(timezone.utc).strftime("%Y%m%d")

    md_path = iv_dir / f"iv_correlation_{datestamp}.md"
    md_path.write_text(md, encoding="utf-8")

    json_path = iv_dir / "latest.json"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )

    # Also write timestamped JSON for history
    json_ts_path = iv_dir / f"iv_correlation_{datestamp}.json"
    json_ts_path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )

    print(f"\nReports written to: {iv_dir}/")
    print(f"  Markdown: {md_path.name}")
    print(f"  JSON:     {json_path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
