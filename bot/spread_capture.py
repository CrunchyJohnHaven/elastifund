#!/usr/bin/env python3
"""Cross-window spread capture scanner for binary UP/DOWN markets.

Instance 14 focuses on identifying windows where buying both complementary
outcomes is underpriced (e.g. UP ask + DOWN ask < 0.98).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

logger = logging.getLogger("spread_capture")

DEFAULT_GAMMA_MARKETS_URL = os.environ.get("BTC5_GAMMA_MARKETS_URL", "https://gamma-api.polymarket.com/markets")
DEFAULT_CLOB_BOOK_URL = os.environ.get("BTC5_CLOB_BOOK_URL", "https://clob.polymarket.com/book")
DEFAULT_SCAN_OUTPUT_PATH = Path("data/spread_arb_scan.json")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _window_seconds_from_env(default: int = 300) -> int:
    raw = os.environ.get("BTC5_WINDOW_SECONDS")
    if raw in (None, ""):
        return int(default)
    parsed = _safe_float(raw, None)
    if parsed is None:
        return int(default)
    candidate = int(parsed)
    if candidate < 60 or candidate % 60 != 0:
        return int(default)
    return candidate


def _parse_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return list(parsed)
    return []


def _normalize_outcome_label(label: str) -> str:
    text = str(label or "").strip().lower()
    if text in {"up", "yes", "true", "higher"}:
        return "UP"
    if text in {"down", "no", "false", "lower"}:
        return "DOWN"
    if "up" in text or "higher" in text or "above" in text:
        return "UP"
    if "down" in text or "lower" in text or "below" in text:
        return "DOWN"
    return text.upper()


def _default_market_slug_prefix(window_seconds: int) -> str:
    asset_slug = str(os.environ.get("BTC5_ASSET_SLUG_PREFIX", "btc")).strip().rstrip("-") or "btc"
    configured = str(os.environ.get("BTC5_MARKET_SLUG_PREFIX", "")).strip().rstrip("-")
    if configured:
        return configured
    return f"{asset_slug}-updown-{max(1, int(window_seconds) // 60)}m"


def current_window_start(now_ts: float | None = None, *, window_seconds: int = 300) -> int:
    now = _safe_float(now_ts, None)
    ts = float(now) if now is not None else datetime.now(timezone.utc).timestamp()
    span = max(60, int(window_seconds))
    return int(ts) // span * span


def market_slug_for_window(window_start_ts: int, *, market_slug_prefix: str, window_seconds: int) -> str:
    prefix = str(market_slug_prefix or "").strip().rstrip("-")
    if "-updown-" not in prefix:
        minutes = max(1, int(window_seconds) // 60)
        prefix = f"{prefix}-updown-{minutes}m"
    return f"{prefix}-{int(window_start_ts)}"


def choose_token_id_for_direction(market: Mapping[str, Any], direction: str) -> str | None:
    want = str(direction or "").strip().upper()
    if want not in {"UP", "DOWN"}:
        return None

    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, Mapping):
                continue
            token_id = str(token.get("token_id") or token.get("clobTokenId") or token.get("id") or "").strip()
            outcome = _normalize_outcome_label(str(token.get("outcome") or token.get("label") or ""))
            if token_id and outcome == want:
                return token_id

    outcomes = _parse_json_list(market.get("outcomes"))
    token_ids = _parse_json_list(market.get("clobTokenIds"))
    if outcomes and token_ids and len(outcomes) == len(token_ids):
        for outcome, token_id in zip(outcomes, token_ids):
            if _normalize_outcome_label(str(outcome)) == want:
                normalized = str(token_id).strip()
                if normalized:
                    return normalized
        if len(token_ids) == 2:
            return str(token_ids[0] if want == "UP" else token_ids[1]).strip() or None
    return None


@dataclass(frozen=True)
class SpreadWindowScan:
    window_start_ts: int
    window_end_ts: int
    slug: str
    market_found: bool
    up_token_id: str | None
    down_token_id: str | None
    up_best_bid: float | None
    up_best_ask: float | None
    down_best_bid: float | None
    down_best_ask: float | None
    combined_best_ask: float | None
    combined_best_bid: float | None
    gross_edge_per_share: float | None
    threshold_edge_per_share: float | None
    qualifies_arb: bool
    two_sided_both_books: bool
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.combined_best_ask is not None:
            payload["combined_best_ask"] = round(float(self.combined_best_ask), 6)
        if self.combined_best_bid is not None:
            payload["combined_best_bid"] = round(float(self.combined_best_bid), 6)
        if self.gross_edge_per_share is not None:
            payload["gross_edge_per_share"] = round(float(self.gross_edge_per_share), 6)
        if self.threshold_edge_per_share is not None:
            payload["threshold_edge_per_share"] = round(float(self.threshold_edge_per_share), 6)
        return payload


class SpreadCaptureScanner:
    """Fetch complementary books and detect underround opportunities."""

    def __init__(
        self,
        *,
        ask_sum_threshold: float = 0.98,
        window_seconds: int | None = None,
        market_slug_prefix: str | None = None,
        gamma_markets_url: str = DEFAULT_GAMMA_MARKETS_URL,
        clob_book_url: str = DEFAULT_CLOB_BOOK_URL,
        timeout_seconds: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.ask_sum_threshold = float(ask_sum_threshold)
        self.window_seconds = int(window_seconds or _window_seconds_from_env())
        self.market_slug_prefix = str(
            market_slug_prefix or _default_market_slug_prefix(self.window_seconds)
        ).strip().rstrip("-")
        self.gamma_markets_url = str(gamma_markets_url)
        self.clob_book_url = str(clob_book_url)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._session = session or requests.Session()
        self._owns_session = session is None

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def fetch_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        try:
            resp = self._session.get(
                self.gamma_markets_url,
                params={"slug": slug, "limit": 5},
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json()
            markets = payload if isinstance(payload, list) else payload.get("data", [])
            if isinstance(markets, list):
                for market in markets:
                    if isinstance(market, Mapping) and str(market.get("slug") or "").strip() == slug:
                        return dict(market)
        except Exception as exc:
            logger.warning("Gamma slug lookup failed for %s: %s", slug, exc)
        return None

    def fetch_book(self, token_id: str) -> dict[str, Any] | None:
        try:
            resp = self._session.get(
                self.clob_book_url,
                params={"token_id": token_id},
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, Mapping):
                return dict(payload)
        except Exception as exc:
            logger.warning("Book fetch failed for token %s: %s", token_id[:12], exc)
        return None

    @staticmethod
    def top_of_book(book: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
        if not isinstance(book, Mapping):
            return None, None
        bids = book.get("bids")
        asks = book.get("asks")

        def _best(levels: Any, *, side: str) -> float | None:
            if not isinstance(levels, list):
                return None
            prices: list[float] = []
            for level in levels:
                if not isinstance(level, Mapping):
                    continue
                price = _safe_float(level.get("price"), None)
                if price is None:
                    continue
                if price < 0.0 or price > 1.0:
                    continue
                prices.append(float(price))
            if not prices:
                return None
            return max(prices) if side == "bid" else min(prices)

        return _best(bids, side="bid"), _best(asks, side="ask")

    def scan_window(self, window_start_ts: int) -> SpreadWindowScan:
        ws = int(window_start_ts)
        window_end_ts = ws + self.window_seconds
        slug = market_slug_for_window(
            ws,
            market_slug_prefix=self.market_slug_prefix,
            window_seconds=self.window_seconds,
        )
        market = self.fetch_market_by_slug(slug)
        if not market:
            return SpreadWindowScan(
                window_start_ts=ws,
                window_end_ts=window_end_ts,
                slug=slug,
                market_found=False,
                up_token_id=None,
                down_token_id=None,
                up_best_bid=None,
                up_best_ask=None,
                down_best_bid=None,
                down_best_ask=None,
                combined_best_ask=None,
                combined_best_bid=None,
                gross_edge_per_share=None,
                threshold_edge_per_share=None,
                qualifies_arb=False,
                two_sided_both_books=False,
                reason="market_not_found",
            )

        up_token_id = choose_token_id_for_direction(market, "UP")
        down_token_id = choose_token_id_for_direction(market, "DOWN")
        if not up_token_id or not down_token_id:
            return SpreadWindowScan(
                window_start_ts=ws,
                window_end_ts=window_end_ts,
                slug=slug,
                market_found=True,
                up_token_id=up_token_id,
                down_token_id=down_token_id,
                up_best_bid=None,
                up_best_ask=None,
                down_best_bid=None,
                down_best_ask=None,
                combined_best_ask=None,
                combined_best_bid=None,
                gross_edge_per_share=None,
                threshold_edge_per_share=None,
                qualifies_arb=False,
                two_sided_both_books=False,
                reason="missing_complementary_token_ids",
            )

        up_book = self.fetch_book(up_token_id)
        down_book = self.fetch_book(down_token_id)
        up_bid, up_ask = self.top_of_book(up_book)
        down_bid, down_ask = self.top_of_book(down_book)

        combined_best_ask = (up_ask + down_ask) if (up_ask is not None and down_ask is not None) else None
        combined_best_bid = (up_bid + down_bid) if (up_bid is not None and down_bid is not None) else None
        gross_edge = (1.0 - combined_best_ask) if combined_best_ask is not None else None
        threshold_edge = (self.ask_sum_threshold - combined_best_ask) if combined_best_ask is not None else None
        qualifies = combined_best_ask is not None and combined_best_ask < self.ask_sum_threshold
        two_sided = (
            up_bid is not None
            and up_ask is not None
            and down_bid is not None
            and down_ask is not None
            and up_bid < up_ask
            and down_bid < down_ask
        )

        reasons: list[str] = []
        if up_book is None or down_book is None:
            reasons.append("book_missing")
        if combined_best_ask is None:
            reasons.append("missing_ask")
        if combined_best_ask is not None and not qualifies:
            reasons.append("combined_ask_above_threshold")
        if qualifies:
            reasons.append("arb_candidate")

        return SpreadWindowScan(
            window_start_ts=ws,
            window_end_ts=window_end_ts,
            slug=slug,
            market_found=True,
            up_token_id=up_token_id,
            down_token_id=down_token_id,
            up_best_bid=up_bid,
            up_best_ask=up_ask,
            down_best_bid=down_bid,
            down_best_ask=down_ask,
            combined_best_ask=combined_best_ask,
            combined_best_bid=combined_best_bid,
            gross_edge_per_share=gross_edge,
            threshold_edge_per_share=threshold_edge,
            qualifies_arb=qualifies,
            two_sided_both_books=two_sided,
            reason="|".join(reasons) if reasons else None,
        )

    def scan_windows(self, window_start_timestamps: Sequence[int]) -> list[SpreadWindowScan]:
        return [self.scan_window(int(window_start_ts)) for window_start_ts in window_start_timestamps]

    def scan_recent_windows(
        self,
        *,
        window_count: int,
        end_window_start_ts: int | None = None,
    ) -> list[SpreadWindowScan]:
        total = max(0, int(window_count))
        if total == 0:
            return []
        if end_window_start_ts is None:
            end_ws = current_window_start(window_seconds=self.window_seconds) - self.window_seconds
        else:
            end_ws = int(end_window_start_ts)
        start_ws = end_ws - ((total - 1) * self.window_seconds)
        windows = [start_ws + (idx * self.window_seconds) for idx in range(total)]
        return self.scan_windows(windows)


def build_spread_arb_report(
    scans: Iterable[SpreadWindowScan],
    *,
    ask_sum_threshold: float,
    window_seconds: int,
    market_slug_prefix: str,
) -> dict[str, Any]:
    rows = list(scans)
    opportunities = [row for row in rows if row.qualifies_arb]
    combined_asks = [float(row.combined_best_ask) for row in rows if row.combined_best_ask is not None]
    best_ask = min(combined_asks) if combined_asks else None
    avg_ask = (sum(combined_asks) / len(combined_asks)) if combined_asks else None
    two_sided_count = sum(1 for row in rows if row.two_sided_both_books)
    quote_complete_count = sum(1 for row in rows if row.combined_best_ask is not None)
    market_found_count = sum(1 for row in rows if row.market_found)
    best_opportunity = None
    if opportunities:
        best_row = max(
            opportunities,
            key=lambda row: float(row.gross_edge_per_share or 0.0),
        )
        best_opportunity = best_row.to_dict()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "ask_sum_threshold": round(float(ask_sum_threshold), 6),
            "window_seconds": int(window_seconds),
            "market_slug_prefix": str(market_slug_prefix),
        },
        "stats": {
            "scanned_windows": len(rows),
            "market_found_windows": market_found_count,
            "quote_complete_windows": quote_complete_count,
            "two_sided_windows": two_sided_count,
            "arb_candidate_windows": len(opportunities),
            "arb_candidate_rate": round(len(opportunities) / len(rows), 6) if rows else 0.0,
            "best_combined_ask": round(best_ask, 6) if best_ask is not None else None,
            "average_combined_ask": round(avg_ask, 6) if avg_ask is not None else None,
        },
        "best_opportunity": best_opportunity,
        "opportunities": [row.to_dict() for row in opportunities],
        "windows": [row.to_dict() for row in rows],
    }


def scan_to_report(
    *,
    output_path: str | Path = DEFAULT_SCAN_OUTPUT_PATH,
    window_count: int = 288,
    ask_sum_threshold: float = 0.98,
    window_seconds: int | None = None,
    market_slug_prefix: str | None = None,
    end_window_start_ts: int | None = None,
    scanner: SpreadCaptureScanner | None = None,
) -> dict[str, Any]:
    owned_scanner = scanner is None
    active_scanner = scanner or SpreadCaptureScanner(
        ask_sum_threshold=ask_sum_threshold,
        window_seconds=window_seconds,
        market_slug_prefix=market_slug_prefix,
    )
    try:
        scans = active_scanner.scan_recent_windows(
            window_count=window_count,
            end_window_start_ts=end_window_start_ts,
        )
        report = build_spread_arb_report(
            scans,
            ask_sum_threshold=active_scanner.ask_sum_threshold,
            window_seconds=active_scanner.window_seconds,
            market_slug_prefix=active_scanner.market_slug_prefix,
        )
    finally:
        if owned_scanner:
            active_scanner.close()

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan BTC 5m/15m windows for dual-sided spread arb candidates.")
    parser.add_argument("--window-count", type=int, default=288, help="Number of closed windows to scan.")
    parser.add_argument(
        "--ask-sum-threshold",
        type=float,
        default=0.98,
        help="Flag windows where UP ask + DOWN ask is below this value.",
    )
    parser.add_argument(
        "--window-seconds",
        type=int,
        default=_window_seconds_from_env(),
        help="Window size in seconds (default uses BTC5_WINDOW_SECONDS or 300).",
    )
    parser.add_argument(
        "--market-slug-prefix",
        default="",
        help="Override market slug prefix (default uses BTC5_MARKET_SLUG_PREFIX/autoderived).",
    )
    parser.add_argument(
        "--end-window-start-ts",
        type=int,
        default=None,
        help="Optional inclusive end window_start_ts. Defaults to most recently closed window.",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_SCAN_OUTPUT_PATH),
        help="JSON report destination.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="HTTP timeout per request.")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR).")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=str(args.log_level).upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scanner = SpreadCaptureScanner(
        ask_sum_threshold=float(args.ask_sum_threshold),
        window_seconds=int(args.window_seconds),
        market_slug_prefix=str(args.market_slug_prefix).strip() or None,
        timeout_seconds=float(args.timeout_seconds),
    )
    try:
        report = scan_to_report(
            output_path=Path(args.output_path),
            window_count=int(args.window_count),
            ask_sum_threshold=float(args.ask_sum_threshold),
            end_window_start_ts=args.end_window_start_ts,
            scanner=scanner,
        )
    finally:
        scanner.close()
    stats = report.get("stats") if isinstance(report, Mapping) else {}
    logger.info(
        "Spread scan complete: windows=%s opportunities=%s best_combined_ask=%s output=%s",
        stats.get("scanned_windows"),
        stats.get("arb_candidate_windows"),
        stats.get("best_combined_ask"),
        args.output_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
