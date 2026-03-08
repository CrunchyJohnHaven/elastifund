from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENABLE_JJ_LIVE_SUITE = "ELASTIFUND_ENABLE_JJ_LIVE_SUITE"
JJ_LIVE_COUPLED_TESTS = {
    "bot/tests/test_ensemble_disagreement.py",
    "bot/tests/test_jj_live_instance6.py",
    "bot/tests/test_jj_live_microstructure.py",
    "tests/test_jj_live_combinatorial.py",
    "tests/test_jj_live_sum_violation.py",
}
OPTIONAL_YAML_TEST = "simulator/tests/test_simulator.py"


def pytest_ignore_collect(collection_path: Path, config) -> bool:
    rel_path = collection_path.relative_to(ROOT).as_posix()

    if (
        rel_path in JJ_LIVE_COUPLED_TESTS
        and os.environ.get(ENABLE_JJ_LIVE_SUITE) != "1"
    ):
        return True

    if rel_path == OPTIONAL_YAML_TEST and importlib.util.find_spec("yaml") is None:
        return True

    return False
