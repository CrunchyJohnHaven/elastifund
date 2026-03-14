from . import _scale_comparison_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})

def test_run_scale_comparison_enriches_with_signal_source_audit(monkeypatch, tmp_path: Path):
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        assumptions=["synthetic llm lane"],
        evidence_summary={"qualified_signals": 10},
        opportunities=[
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "NO_WON", timestamp="2026-03-08T00:05:00Z"),
        ],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": ready_lane,
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    audit_path = tmp_path / "signal_source_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "btc_fast_window_confirmation": {
                    "status": "ready",
                    "summary": {
                        "ready_sources": ["wallet_flow"],
                        "best_source_by_confirmation_lift": "wallet_flow",
                        "confirmation_coverage_ratio": 0.6,
                        "confirmation_resolved_window_coverage": 0.6,
                        "confirmation_executed_window_coverage": 0.4,
                        "confirmation_false_suppression_cost_usd": 0.5,
                        "confirmation_lift_avg_pnl_usd": 1.25,
                        "confirmation_lift_win_rate": 0.15,
                        "confirmation_contradiction_penalty": 0.2,
                    },
                },
                "wallet_flow_vs_llm": {
                    "status": "ready",
                    "winner": "wallet_flow",
                    "wallet_flow_any_win_rate_delta_vs_llm_only": 0.05,
                },
                "combined_sources_vs_single_source": {
                    "status": "ready",
                    "winner": "combined",
                    "combined_sources_beat_single_source_lanes": True,
                },
                "by_source_combo": {
                    "llm": {"win_rate": 0.50},
                    "wallet_flow": {"win_rate": 0.62},
                    "llm+wallet_flow": {"win_rate": 0.70},
                },
                "ranking_snapshot": {
                    "best_component_source": {"source": "wallet_flow", "win_rate": 0.62},
                    "best_source_combo": {"source_combo": "llm+wallet_flow", "win_rate": 0.70},
                },
                "capital_ranking_support": {
                    "stale_threshold_hours": 6.0,
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "ready",
                    "combined_sources_vs_single_source_status": "ready",
                    "best_component_source": "wallet_flow",
                    "best_source_combo": "llm+wallet_flow",
                    "capital_expansion_support_status": "ready",
                    "stage_upgrade_support_status": "ready",
                    "btc_fast_window_confirmation_ready": True,
                    "confirmation_support_status": "ready",
                    "confirmation_sources_ready": ["wallet_flow"],
                    "best_confirmation_source": "wallet_flow",
                    "confirmation_coverage_ratio": 0.6,
                    "confirmation_resolved_window_coverage": 0.6,
                    "confirmation_executed_window_coverage": 0.4,
                    "confirmation_false_suppression_cost_usd": 0.5,
                    "confirmation_lift_avg_pnl_usd": 1.25,
                    "confirmation_lift_win_rate": 0.15,
                    "confirmation_contradiction_penalty": 0.2,
                    "confirmation_blocking_checks": [],
                },
            }
        )
    )

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "out.json",
        markdown_output_path=tmp_path / "out.md",
        signal_source_audit_path=audit_path,
    )

    source_evidence = report["scoreboard"]["llm_only"]["source_evidence"]
    assert source_evidence["signal_source_audit_loaded"] is True
    assert source_evidence["wallet_flow_beats_llm_only"] is True
    assert source_evidence["combined_sources_beat_single_source_lanes"] is True
    assert report["source_audit"]["capital_ranking_support"]["trade_attribution_ready"] is True
    assert report["source_audit"]["btc_fast_window_confirmation"]["status"] == "ready"
    assert source_evidence["lane_source_status"] == "lagging"
    assert report["scoreboard"]["wallet_flow"]["source_evidence"]["lane_source_status"] == "winning"
    assert report["scoreboard"]["combined"]["source_evidence"]["lane_source_status"] == "winning"


def test_run_scale_comparison_uses_confirmation_metrics_in_btc5_ranking(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 10, 13, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        evidence_summary={"qualified_signals": 2},
        opportunities=[
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "NO_WON", timestamp="2026-03-10T12:05:00Z"),
        ],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": LaneEvidence(
                lane="wallet_flow",
                status="insufficient_data",
                reasons=["zero qualifying signals"],
                evidence_summary={"resolved_qualifying_signals": 0},
            ),
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    paths = _write_capital_surface_fixtures(
        tmp_path,
        runtime_generated_at="2026-03-10T12:55:00+00:00",
        forecast_generated_at="2026-03-10T12:54:00+00:00",
    )
    monte_carlo_path = _write_capacity_stress_fixture(tmp_path / "btc5_monte_carlo_latest.json")
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Buy","5.0","10.0","Down","1773137400","0x1"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Redeem","0","0","","1773137700","0x2"',
            ]
        )
        + "\n"
    )
    probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    _write_probe_db(probe_db_path, _probe_rows(live_filled=12, failed=2, start_ts=1773147300))

    positive_report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "positive.json",
        markdown_output_path=tmp_path / "positive.md",
        signal_source_audit_path=_write_ready_signal_audit(tmp_path / "signal_source_audit_positive.json"),
        btc5_monte_carlo_path=monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )
    negative_report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "negative.json",
        markdown_output_path=tmp_path / "negative.md",
        signal_source_audit_path=_write_negative_confirmation_signal_audit(
            tmp_path / "signal_source_audit_negative.json"
        ),
        btc5_monte_carlo_path=monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )

    positive_btc5 = next(item for item in positive_report["venue_scoreboard"] if item["venue"] == "polymarket")
    negative_btc5 = next(item for item in negative_report["venue_scoreboard"] if item["venue"] == "polymarket")

    assert positive_btc5["capital_status"] == "ready_scale"
    assert negative_btc5["capital_status"] == "ready_scale"
    assert positive_btc5["confirmation_support"]["status"] == "ready"
    assert negative_btc5["confirmation_support"]["status"] == "ready"
    assert positive_btc5["confidence_label"] == "high"
    assert negative_btc5["confidence_label"] == "medium"
    assert positive_btc5["ranking_score"] > negative_btc5["ranking_score"]
    assert positive_btc5["confirmation_support"]["lift_avg_pnl_usd"] == 1.8
    assert positive_btc5["confirmation_support"]["false_suppression_cost_usd"] == 0.25
    assert negative_btc5["confirmation_support"]["lift_avg_pnl_usd"] == -1.5
    assert negative_btc5["confirmation_support"]["false_suppression_cost_usd"] == 6.0


def test_run_scale_comparison_drops_confidence_when_confirmation_coverage_is_weak(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 10, 13, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        evidence_summary={"qualified_signals": 2},
        opportunities=[
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "NO_WON", timestamp="2026-03-10T12:05:00Z"),
        ],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": LaneEvidence(
                lane="wallet_flow",
                status="insufficient_data",
                reasons=["zero qualifying signals"],
                evidence_summary={"resolved_qualifying_signals": 0},
            ),
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    paths = _write_capital_surface_fixtures(
        tmp_path,
        runtime_generated_at="2026-03-10T12:55:00+00:00",
        forecast_generated_at="2026-03-10T12:54:00+00:00",
    )
    monte_carlo_path = _write_capacity_stress_fixture(tmp_path / "btc5_monte_carlo_latest.json")
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Buy","5.0","10.0","Down","1773137400","0x1"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Redeem","0","0","","1773137700","0x2"',
            ]
        )
        + "\n"
    )
    probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    _write_probe_db(probe_db_path, _probe_rows(live_filled=12, failed=2, start_ts=1773147300))

    strong_report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "strong.json",
        markdown_output_path=tmp_path / "strong.md",
        signal_source_audit_path=_write_ready_signal_audit(tmp_path / "signal_source_audit_strong.json"),
        btc5_monte_carlo_path=monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )
    weak_report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "weak.json",
        markdown_output_path=tmp_path / "weak.md",
        signal_source_audit_path=_write_weak_coverage_signal_audit(
            tmp_path / "signal_source_audit_weak.json"
        ),
        btc5_monte_carlo_path=monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )

    strong_btc5 = next(item for item in strong_report["venue_scoreboard"] if item["venue"] == "polymarket")
    weak_btc5 = next(item for item in weak_report["venue_scoreboard"] if item["venue"] == "polymarket")

    assert strong_btc5["capital_status"] == "ready_scale"
    assert weak_btc5["capital_status"] == "ready_scale"
    assert strong_btc5["confidence_label"] == "high"
    assert weak_btc5["confidence_label"] == "medium"
    assert weak_btc5["capital_confidence"]["coverage_label"] == "weak"
    assert weak_btc5["confirmation_support"]["coverage_label"] == "weak"
    assert weak_btc5["ranking_score"] < strong_btc5["ranking_score"]
    assert weak_report["capital_allocation_recommendation"]["next_1000_usd"]["status"] == "ready_scale"
    assert weak_report["capital_allocation_recommendation"]["next_1000_usd"]["confidence_label"] == "medium"
