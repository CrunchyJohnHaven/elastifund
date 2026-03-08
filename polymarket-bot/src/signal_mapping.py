"""Utilities for mapping external analyzer output into internal trade signals."""

from __future__ import annotations

import math
import os


def _float_env(name: str, default: str) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


PLATT_A = _float_env("PLATT_A", "0.5914")
PLATT_B = _float_env("PLATT_B", "-0.3977")

YES_THRESHOLD = 0.15
NO_THRESHOLD = 0.05

TAKER_FEE_RATES = {
    "crypto": 0.025,
    "sports": 0.007,
    "default": 0.0,
}


def _safe_float(value, default: float = 0.5):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_confidence(value) -> float:
    """Normalize mixed confidence payloads into [0, 1]."""
    if isinstance(value, str):
        conf_map = {"high": 0.85, "medium": 0.6, "med": 0.6, "low": 0.3}
        return conf_map.get(value.lower().strip(), 0.5)
    return max(0.0, min(1.0, _safe_float(value, 0.5)))


def map_vps_signal_direction(result: dict, market_price: float) -> str:
    """Map VPS analyzer direction/signal fields into buy_yes/buy_no/hold."""
    direction = str(result.get("direction", "") or "").strip().lower()
    if direction in ("buy_yes", "buy_no", "hold"):
        return direction

    signal = str(result.get("signal", result.get("action", "hold")) or "").strip().upper()
    if signal in ("NO", "BUY_NO", "SELL", "SHORT"):
        return "buy_no"
    if signal in ("BUY", "YES", "BUY_YES"):
        est_prob = _safe_float(
            result.get("estimated_prob", result.get("probability", 0.5)),
            0.5,
        )
        return "buy_yes" if est_prob >= market_price else "buy_no"
    return "hold"


def calculate_taker_fee(price: float, category: str) -> float:
    rate = TAKER_FEE_RATES.get(category, TAKER_FEE_RATES["default"])
    return price * (1 - price) * rate


def calibrate_probability(raw_prob: float) -> float:
    raw_prob = max(0.001, min(0.999, raw_prob))
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability(1.0 - raw_prob)
    logit_input = math.log(raw_prob / (1 - raw_prob))
    logit_output = PLATT_A * logit_input + PLATT_B
    logit_output = max(-30, min(30, logit_output))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


def compute_calibrated_signal(
    raw_prob: float,
    market_price: float,
    category: str,
    *,
    already_calibrated: bool = False,
) -> dict:
    calibrated = raw_prob if already_calibrated else calibrate_probability(raw_prob)
    calibrated = max(0.01, min(0.99, calibrated))

    raw_edge = calibrated - market_price
    buy_price = market_price if raw_edge > 0 else (1 - market_price)
    taker_fee = calculate_taker_fee(buy_price, category)
    net_edge = abs(raw_edge) - taker_fee

    if raw_edge > 0 and net_edge >= YES_THRESHOLD:
        direction = "buy_yes"
        mispriced = True
    elif raw_edge < 0 and net_edge >= NO_THRESHOLD:
        direction = "buy_no"
        mispriced = True
    else:
        direction = "hold"
        mispriced = False
        net_edge = 0.0

    return {
        "mispriced": mispriced,
        "direction": direction,
        "edge": net_edge,
        "raw_edge": raw_edge,
        "calibrated_prob": calibrated,
        "taker_fee": taker_fee,
        "category": category,
    }
