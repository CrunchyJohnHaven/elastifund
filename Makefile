PYTHON ?= python3

.PHONY: help bootstrap bootstrap-lite bootstrap-runtime doctor onboard quickstart preflight hygiene verify-static verify-fastpath test-select test-fixture-ownership test-research-sim test-platform test verify test-root test-polymarket test-nontrading smoke-nontrading btc5-autoresearch-local btc5-autoresearch-local-autopush btc5-arr-report btc5-hypothesis-lab btc5-regime-policy-lab btc5-hypothesis-frontier strike-factory-local deploy-write-manifest deploy-dry-run api-specs analyze-iv clean

help:
	@printf '%s\n' \
		'bootstrap        Install root development dependencies' \
		'bootstrap-lite   Install lightweight docs/static dependencies' \
		'bootstrap-runtime Install runtime dependencies without test extras' \
		'doctor           Run local setup diagnostics' \
		'onboard          Generate .env and runtime defaults for a fresh clone' \
		'quickstart       Prepare .env and launch the local Docker stack' \
		'preflight        Run Elastifund env preflight checks' \
		'hygiene          Run repo hygiene checks' \
		'verify-static    Run docs/static verification checks' \
		'verify-fastpath  Run verify-static + manifest freshness checks' \
		'test-select      Print suggested local test commands for current diff' \
		'test-fixture-ownership Run fixture ownership contract tests' \
		'test-research-sim Run research/simulation regression slice' \
		'test-platform    Run hub/platform regression slice' \
		'test             Run the root regression suite' \
		'verify           Run hygiene + root tests + polymarket-bot tests' \
		'test-root        Run the repo-root pytest matrix' \
		'test-nontrading  Run the nontrading test suite only' \
		'smoke-nontrading Run the deterministic nontrading smoke check' \
		'btc5-autoresearch-local Run the local 5-minute BTC5 autoresearch loop' \
		'btc5-autoresearch-local-autopush Run the local loop and auto-push allowlisted ARR promotions' \
		'btc5-arr-report  Render tracked percentage-only ARR progress artifacts' \
		'btc5-hypothesis-lab Run the BTC5 walk-forward hypothesis generator' \
		'btc5-regime-policy-lab Run the BTC5 regime-conditioned policy search' \
		'btc5-hypothesis-frontier Render the tracked BTC5 hypothesis frontier artifacts' \
		'strike-factory-local Run the revenue-first strike factory cycle' \
		'deploy-write-manifest Regenerate the release manifest from current machine truth' \
		'deploy-dry-run   Refresh bridge state, regenerate the manifest, and run the VPS deploy dry-run' \
		'test-polymarket  Run the nested polymarket-bot test suite' \
		'api-specs        Regenerate OpenAPI specs' \
		'analyze-iv       Run Deribit IV correlation analysis on BTC5 data' \
		'clean            Remove Python/test/Finder caches'

bootstrap:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

bootstrap-lite:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-lite.txt

bootstrap-runtime:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt -r hub/requirements.txt

doctor:
	$(PYTHON) scripts/doctor.py

onboard:
	$(PYTHON) scripts/elastifund_setup.py --non-interactive

quickstart:
	$(PYTHON) scripts/quickstart.py

preflight:
	$(PYTHON) scripts/elastifund_setup.py --check

hygiene:
	$(PYTHON) scripts/check_repo_hygiene.py
	$(PYTHON) scripts/check_docs_indexes.py
	$(PYTHON) scripts/check_static_routes.py
	$(PYTHON) scripts/check_shell_help.py
	$(PYTHON) scripts/render_scripts_index.py --check
	$(PYTHON) scripts/render_deprecation_candidates.py --check

verify-static:
	$(MAKE) hygiene
	$(PYTHON) -m pytest -q tests/test_select_test_targets.py tests/test_reports_layout_contract.py tests/test_reports_top_level_symlink_collapse.py tests/test_reports_top_level_symlink_prune.py tests/test_reports_symlink_collapse.py

verify-fastpath:
	$(MAKE) hygiene
	$(PYTHON) scripts/render_repo_manifest.py --check
	$(PYTHON) -m pytest -q tests/test_select_test_targets.py tests/test_reports_layout_contract.py tests/test_reports_top_level_symlink_collapse.py tests/test_reports_top_level_symlink_prune.py tests/test_reports_symlink_collapse.py

test-select:
	$(PYTHON) scripts/select_test_targets.py --from-git-status --format commands

test-fixture-ownership:
	$(PYTHON) -m pytest tests/test_fixture_ownership_contract.py -q

test-research-sim:
	$(PYTHON) -m pytest tests/test_backtest.py tests/test_kalshi_weather_simulator.py tests/test_queue_fill_model.py -q

test-platform:
	$(PYTHON) -m pytest hub/tests -q

test:
	$(PYTHON) scripts/run_root_tests.py

verify:
	$(MAKE) hygiene
	$(PYTHON) scripts/run_root_tests.py
	cd polymarket-bot && $(PYTHON) -m pytest tests -q

test-root:
	$(PYTHON) -m pytest -q

test-nontrading:
	$(PYTHON) -m pytest nontrading/tests -q

smoke-nontrading:
	$(PYTHON) scripts/nontrading_smoke.py

btc5-autoresearch-local:
	$(PYTHON) scripts/run_btc5_autoresearch_loop.py --include-archive-csvs
	@printf '%s\n' 'Latest package decision (reports/btc5_autoresearch_loop/latest.md):'
	@grep -E 'Last package decision|Last package confidence|Last missing evidence|Last public forecast source|Last capital status|Last capital tranche' reports/btc5_autoresearch_loop/latest.md || true

btc5-autoresearch-local-autopush:
	$(PYTHON) scripts/run_btc5_autoresearch_loop.py --include-archive-csvs --on-promote-command "$(PYTHON) scripts/btc5_autoresearch_autopush.py"
	@printf '%s\n' 'Latest package decision (reports/btc5_autoresearch_loop/latest.md):'
	@grep -E 'Last package decision|Last package confidence|Last missing evidence|Last public forecast source|Last capital status|Last capital tranche' reports/btc5_autoresearch_loop/latest.md || true

btc5-arr-report:
	$(PYTHON) scripts/render_btc5_arr_progress.py

btc5-hypothesis-lab:
	$(PYTHON) scripts/btc5_hypothesis_lab.py --include-archive-csvs

btc5-regime-policy-lab:
	$(PYTHON) scripts/btc5_regime_policy_lab.py --include-archive-csvs

btc5-hypothesis-frontier:
	$(PYTHON) scripts/render_btc5_hypothesis_frontier.py

strike-factory-local:
	$(PYTHON) scripts/run_strike_factory.py

deploy-write-manifest:
	$(PYTHON) scripts/deploy_release_bundle.py --write-manifest

deploy-dry-run:
	$(PYTHON) deploy/dry_run.py

test-polymarket:
	cd polymarket-bot && $(PYTHON) -m pytest tests -q

analyze-iv:
	$(PYTHON) scripts/analyze_iv_edge.py --db-path data/btc_5min_maker.db

api-specs:
	$(PYTHON) scripts/export_openapi_specs.py

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) -delete
