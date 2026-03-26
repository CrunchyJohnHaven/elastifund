from __future__ import annotations
import os
import logging
import orjson
from typing import Any
from server.config import REPORTS_DIR, DATA_DIR, STATE_DIR

logger = logging.getLogger(__name__)


def _read_json(path: str) -> Any:
    try:
        with open(path, 'rb') as f:
            return orjson.loads(f.read())
    except FileNotFoundError:
        logger.debug(f"File not found: {path}")
        return None
    except Exception as e:
        logger.error(f"Failed to read {path}: {e}")
        return None


def get_health() -> dict:
    result = _read_json(os.path.join(REPORTS_DIR, 'btc5_health_latest.json'))
    return result if isinstance(result, dict) else {}


def get_cohort() -> dict:
    result = _read_json(os.path.join(REPORTS_DIR, 'btc5_validation_cohort_latest.json'))
    return result if isinstance(result, dict) else {}


def get_filter_economics() -> dict:
    result = _read_json(os.path.join(REPORTS_DIR, 'btc5_filter_economics_latest.json'))
    return result if isinstance(result, dict) else {}


def get_runtime_contract() -> dict:
    result = _read_json(os.path.join(REPORTS_DIR, 'btc5_runtime_contract.json'))
    return result if isinstance(result, dict) else {}


def get_autoresearch_results() -> list[dict]:
    result = _read_json(os.path.join(DATA_DIR, 'autoresearch_results.json'))
    if isinstance(result, list):
        return result
    return []


def get_cohort_contract() -> dict:
    result = _read_json(os.path.join(STATE_DIR, 'btc5_validation_cohort.json'))
    return result if isinstance(result, dict) else {}


def get_active_mutation() -> dict:
    result = _read_json(os.path.join(STATE_DIR, 'btc5_active_mutation.json'))
    return result if isinstance(result, dict) else {}


def get_latest_monte_carlo() -> dict:
    """Find and return the most recent monte carlo report."""
    try:
        candidates = [
            f for f in os.listdir(REPORTS_DIR)
            if f.startswith('monte_carlo') and f.endswith('.json')
        ]
        if not candidates:
            return {}
        candidates.sort(reverse=True)
        result = _read_json(os.path.join(REPORTS_DIR, candidates[0]))
        return result if isinstance(result, dict) else {}
    except Exception as e:
        logger.error(f"get_latest_monte_carlo error: {e}")
        return {}
