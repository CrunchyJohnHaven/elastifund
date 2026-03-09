PYTHON ?= python3

.PHONY: help bootstrap doctor onboard quickstart preflight hygiene test verify test-root test-polymarket test-nontrading smoke-nontrading btc5-autoresearch-local btc5-autoresearch-local-autopush btc5-arr-report btc5-hypothesis-lab btc5-regime-policy-lab btc5-hypothesis-frontier deploy-write-manifest deploy-dry-run api-specs clean

help:
	@printf '%s\n' \
		'bootstrap        Install root development dependencies' \
		'doctor           Run local setup diagnostics' \
		'onboard          Generate .env and runtime defaults for a fresh clone' \
		'quickstart       Prepare .env and launch the local Docker stack' \
		'preflight        Run Elastifund env preflight checks' \
		'hygiene          Run repo hygiene checks' \
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
		'deploy-write-manifest Regenerate the release manifest from current machine truth' \
		'deploy-dry-run   Refresh bridge state, regenerate the manifest, and run the VPS deploy dry-run' \
		'test-polymarket  Run the nested polymarket-bot test suite' \
		'api-specs        Regenerate OpenAPI specs' \
		'clean            Remove Python/test/Finder caches'

bootstrap:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

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

test:
	$(PYTHON) scripts/run_root_tests.py

verify:
	$(PYTHON) scripts/check_repo_hygiene.py
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

btc5-autoresearch-local-autopush:
	$(PYTHON) scripts/run_btc5_autoresearch_loop.py --include-archive-csvs --on-promote-command "$(PYTHON) scripts/btc5_autoresearch_autopush.py"

btc5-arr-report:
	$(PYTHON) scripts/render_btc5_arr_progress.py

btc5-hypothesis-lab:
	$(PYTHON) scripts/btc5_hypothesis_lab.py --include-archive-csvs

btc5-regime-policy-lab:
	$(PYTHON) scripts/btc5_regime_policy_lab.py --include-archive-csvs

btc5-hypothesis-frontier:
	$(PYTHON) scripts/render_btc5_hypothesis_frontier.py

deploy-write-manifest:
	$(PYTHON) scripts/deploy_release_bundle.py --write-manifest

deploy-dry-run:
	$(PYTHON) deploy/dry_run.py

test-polymarket:
	cd polymarket-bot && $(PYTHON) -m pytest tests -q

api-specs:
	$(PYTHON) scripts/export_openapi_specs.py

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) -delete
