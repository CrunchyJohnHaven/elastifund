from inventory.methodology import methodology_payload
from inventory.service import bot_detail_payload, list_bots_payload, paper_status_payload, rankings_payload


def test_methodology_payload_exposes_t0_to_t7():
    payload = methodology_payload()

    assert payload["spec_version"] == "2026.03-candidate1"
    assert [item["id"] for item in payload["test_matrix"]] == [
        "T0",
        "T1",
        "T2",
        "T3",
        "T4",
        "T5",
        "T6",
        "T7",
    ]


def test_list_bots_payload_filters_open_source_execution_cohort():
    payload = list_bots_payload(category="open_source_execution")
    ids = {item["id"] for item in payload["items"]}

    assert {"freqtrade", "hummingbot", "jesse", "octobot"} <= ids
    assert payload["summary"]["by_category"] == {"open_source_execution": payload["summary"]["total"]}


def test_bot_detail_payload_includes_latest_run():
    payload = bot_detail_payload("freqtrade")

    assert payload["bot"]["name"] == "Freqtrade"
    assert payload["latest_run"]["id"] == "freqtrade-cycle3-t0-t5"
    assert payload["paper_status"]["state"] == "not_started"


def test_rankings_payload_is_methodology_only_until_completed_runs_exist():
    payload = rankings_payload()

    assert payload["state"] == "methodology_only"
    assert payload["items"] == []
    assert "Methodology is published" in payload["message"]


def test_paper_status_payload_can_filter_by_bot():
    payload = paper_status_payload(bot_id="hummingbot")

    assert payload["state"] == "not_started"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["bot_id"] == "hummingbot"


def test_bot_detail_payload_exposes_comparison_only_system() -> None:
    payload = bot_detail_payload("openclaw")

    assert payload["bot"]["benchmark_status"] == "comparison_only"
    assert payload["latest_run"]["id"] == "openclaw-cycle3-comparison-only"
    assert payload["latest_run"]["comparison_mode"] == "comparison_only"
