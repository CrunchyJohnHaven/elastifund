from scripts.select_test_targets import route_paths, suggest_targets


def test_docs_only_paths_use_verify_static() -> None:
    targets = suggest_targets(["docs/README.md", "index.html"])
    assert targets == ["make verify-static"]


def test_build_route_paths_use_verify_static() -> None:
    targets = suggest_targets(["build/index.html"])
    assert targets == ["make verify-static"]


def test_scripts_metadata_paths_use_verify_fastpath() -> None:
    targets = suggest_targets(["scripts/DEPRECATION_CANDIDATES.md"])
    assert targets == ["make verify-fastpath"]


def test_package_map_paths_use_verify_fastpath() -> None:
    targets = suggest_targets(["agent/PACKAGE_MAP.md"])
    assert targets == ["make verify-fastpath"]


def test_requirements_lite_change_uses_verify_fastpath() -> None:
    targets = suggest_targets(["requirements-lite.txt"])
    assert targets == ["make verify-fastpath"]


def test_runtime_path_still_routes_to_heavy_verification() -> None:
    targets = suggest_targets(["bot/jj_live.py"])
    assert targets == ["make hygiene", "make test"]


def test_research_sim_path_routes_to_research_lane() -> None:
    route = route_paths(["backtest/run_scale_comparison.py"])
    assert route["run_research_sim"] is True
    assert route["run_root"] is False
    assert route["run_platform"] is False
    assert route["local_commands"] == ["make hygiene", "make test-research-sim"]


def test_platform_path_routes_to_platform_lane() -> None:
    route = route_paths(["hub/app.py"])
    assert route["run_research_sim"] is False
    assert route["run_root"] is False
    assert route["run_platform"] is True
    assert route["local_commands"] == ["make hygiene", "make test-platform"]


def test_nontrading_path_routes_to_nontrading_only() -> None:
    route = route_paths(["nontrading/finance/main.py"])
    assert route["run_nontrading"] is True
    assert route["run_root"] is False
    assert route["run_polymarket"] is False
    assert route["local_commands"] == ["make hygiene", "make test-nontrading"]


def test_polymarket_path_routes_to_polymarket_only() -> None:
    route = route_paths(["polymarket-bot/src/main.py"])
    assert route["run_nontrading"] is False
    assert route["run_root"] is False
    assert route["run_polymarket"] is True
    assert route["local_commands"] == ["make hygiene", "make test-polymarket"]


def test_requirements_change_routes_to_all_heavy_lanes() -> None:
    route = route_paths(["requirements.txt"])
    assert route["run_research_sim"] is True
    assert route["run_platform"] is True
    assert route["run_nontrading"] is False
    assert route["run_root"] is True
    assert route["run_polymarket"] is True
    assert route["local_commands"] == [
        "make hygiene",
        "make test-research-sim",
        "make test-platform",
        "make test",
        "make test-polymarket",
    ]
