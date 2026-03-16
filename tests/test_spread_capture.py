from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.spread_capture import (
    SpreadCaptureScanner,
    SpreadWindowScan,
    build_spread_arb_report,
    choose_token_id_for_direction,
    scan_to_report,
)


class _StubScanner(SpreadCaptureScanner):
    def __init__(self, *, markets: dict[str, dict], books: dict[str, dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self._markets = markets
        self._books = books

    def fetch_market_by_slug(self, slug: str) -> dict | None:
        market = self._markets.get(slug)
        return dict(market) if isinstance(market, dict) else None

    def fetch_book(self, token_id: str) -> dict | None:
        book = self._books.get(token_id)
        return dict(book) if isinstance(book, dict) else None


def test_choose_token_id_for_direction_falls_back_to_clob_token_ids() -> None:
    market = {
        "outcomes": '["UP","DOWN"]',
        "clobTokenIds": '["token-up","token-down"]',
    }
    assert choose_token_id_for_direction(market, "UP") == "token-up"
    assert choose_token_id_for_direction(market, "DOWN") == "token-down"


def test_scan_window_flags_arb_candidate_when_asks_under_threshold() -> None:
    window_start_ts = 1710000000
    slug = f"btc-updown-5m-{window_start_ts}"
    scanner = _StubScanner(
        markets={
            slug: {
                "slug": slug,
                "tokens": [
                    {"outcome": "UP", "token_id": "up-token"},
                    {"outcome": "DOWN", "token_id": "down-token"},
                ],
            }
        },
        books={
            "up-token": {"bids": [{"price": 0.04}], "asks": [{"price": 0.06}]},
            "down-token": {"bids": [{"price": 0.86}], "asks": [{"price": 0.88}]},
        },
        ask_sum_threshold=0.98,
        window_seconds=300,
        market_slug_prefix="btc-updown-5m",
    )

    scan = scanner.scan_window(window_start_ts)

    assert scan.qualifies_arb is True
    assert scan.two_sided_both_books is True
    assert scan.combined_best_ask == pytest.approx(0.94)
    assert scan.gross_edge_per_share == pytest.approx(0.06)
    assert scan.reason is not None and "arb_candidate" in scan.reason


def test_build_spread_arb_report_summarizes_candidates() -> None:
    scans = [
        SpreadWindowScan(
            window_start_ts=1710000000,
            window_end_ts=1710000300,
            slug="btc-updown-5m-1710000000",
            market_found=True,
            up_token_id="up",
            down_token_id="down",
            up_best_bid=0.04,
            up_best_ask=0.06,
            down_best_bid=0.86,
            down_best_ask=0.88,
            combined_best_ask=0.94,
            combined_best_bid=0.90,
            gross_edge_per_share=0.06,
            threshold_edge_per_share=0.04,
            qualifies_arb=True,
            two_sided_both_books=True,
            reason="arb_candidate",
        ),
        SpreadWindowScan(
            window_start_ts=1710000300,
            window_end_ts=1710000600,
            slug="btc-updown-5m-1710000300",
            market_found=True,
            up_token_id="up2",
            down_token_id="down2",
            up_best_bid=0.07,
            up_best_ask=0.09,
            down_best_bid=0.90,
            down_best_ask=0.92,
            combined_best_ask=1.01,
            combined_best_bid=0.97,
            gross_edge_per_share=-0.01,
            threshold_edge_per_share=-0.03,
            qualifies_arb=False,
            two_sided_both_books=True,
            reason="combined_ask_above_threshold",
        ),
    ]
    report = build_spread_arb_report(
        scans,
        ask_sum_threshold=0.98,
        window_seconds=300,
        market_slug_prefix="btc-updown-5m",
    )
    assert report["stats"]["scanned_windows"] == 2
    assert report["stats"]["arb_candidate_windows"] == 1
    assert report["stats"]["best_combined_ask"] == 0.94
    assert report["best_opportunity"]["window_start_ts"] == 1710000000


def test_scan_to_report_writes_json_payload(tmp_path: Path) -> None:
    window_start_ts = 1710000000
    slug = f"btc-updown-5m-{window_start_ts}"
    scanner = _StubScanner(
        markets={
            slug: {
                "slug": slug,
                "tokens": [
                    {"outcome": "UP", "token_id": "up-token"},
                    {"outcome": "DOWN", "token_id": "down-token"},
                ],
            }
        },
        books={
            "up-token": {"bids": [{"price": 0.05}], "asks": [{"price": 0.07}]},
            "down-token": {"bids": [{"price": 0.86}], "asks": [{"price": 0.89}]},
        },
        ask_sum_threshold=0.98,
        window_seconds=300,
        market_slug_prefix="btc-updown-5m",
    )
    output_path = tmp_path / "spread_arb_scan.json"
    payload = scan_to_report(
        output_path=output_path,
        window_count=1,
        ask_sum_threshold=0.98,
        end_window_start_ts=window_start_ts,
        scanner=scanner,
    )

    assert output_path.exists()
    loaded = json.loads(output_path.read_text())
    assert loaded["stats"]["scanned_windows"] == 1
    assert loaded["stats"]["arb_candidate_windows"] == 1
    assert payload["stats"]["best_combined_ask"] == 0.96
