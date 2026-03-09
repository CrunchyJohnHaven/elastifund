PYTHON ?= python3

.PHONY: help bootstrap doctor onboard quickstart preflight hygiene test verify test-root test-polymarket test-nontrading smoke-nontrading api-specs clean

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

test-polymarket:
	cd polymarket-bot && $(PYTHON) -m pytest tests -q

api-specs:
	$(PYTHON) scripts/export_openapi_specs.py

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) -delete
