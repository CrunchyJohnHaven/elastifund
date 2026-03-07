"""
Weather Bracket Arbitrage — Rounding Model & Discrepancy Finder

The core hypothesis: NWS Daily Climate Reports derive from ASOS METAR readings
where Celsius is rounded to integer BEFORE converting to Fahrenheit. This double-
rounding can produce different results than the single-rounding consumer apps use.

This module implements both rounding protocols, maps all discrepancy zones, and
provides the foundation for the backtest.
"""

import math
from typing import Tuple, List, Dict


# --- Rounding Protocol Variants ---

def nws_standard_rounding(celsius_raw: float) -> int:
    """
    NWS protocol with standard rounding (0.5 rounds UP).
    Step 1: Round Celsius to nearest integer (0.5 → up)
    Step 2: Convert to Fahrenheit
    Step 3: Round to nearest integer (0.5 → up)
    """
    celsius_rounded = math.floor(celsius_raw + 0.5)  # Standard rounding
    fahrenheit = celsius_rounded * 9.0 / 5.0 + 32.0
    return math.floor(fahrenheit + 0.5)


def nws_bankers_rounding(celsius_raw: float) -> int:
    """
    NWS protocol with Python's banker's rounding (0.5 → nearest even).
    """
    celsius_rounded = round(celsius_raw)  # Python built-in = banker's rounding
    fahrenheit = celsius_rounded * 9.0 / 5.0 + 32.0
    return round(fahrenheit)


def nws_truncation(celsius_raw: float) -> int:
    """
    NWS protocol if they truncate (floor) instead of rounding.
    """
    if celsius_raw >= 0:
        celsius_int = int(celsius_raw)
    else:
        celsius_int = int(celsius_raw) - (1 if celsius_raw != int(celsius_raw) else 0)
    fahrenheit = celsius_int * 9.0 / 5.0 + 32.0
    return math.floor(fahrenheit + 0.5)


def nws_metar_integer(celsius_int: int) -> int:
    """
    If the METAR report already provides integer Celsius (which it does —
    METAR temperatures are reported as integers), no initial rounding needed.
    Just convert and round.
    """
    fahrenheit = celsius_int * 9.0 / 5.0 + 32.0
    return math.floor(fahrenheit + 0.5)


def consumer_app_fahrenheit(celsius_raw: float) -> int:
    """
    Consumer weather apps: convert directly C→F, round once.
    No intermediate Celsius rounding.
    """
    fahrenheit = celsius_raw * 9.0 / 5.0 + 32.0
    return math.floor(fahrenheit + 0.5)  # Standard rounding


def consumer_app_bankers(celsius_raw: float) -> int:
    """Consumer apps with banker's rounding."""
    fahrenheit = celsius_raw * 9.0 / 5.0 + 32.0
    return round(fahrenheit)


# --- Discrepancy Mapping ---

def find_all_discrepancies(
    c_min: float = -20.0,
    c_max: float = 50.0,
    step: float = 0.1,
    nws_func=nws_standard_rounding,
    consumer_func=consumer_app_fahrenheit
) -> List[Dict]:
    """
    For every temperature increment, compare NWS vs consumer rounding.
    Returns list of discrepancy records.
    """
    discrepancies = []
    c = c_min
    while c <= c_max + step / 2:
        nws_f = nws_func(c)
        con_f = consumer_func(c)
        if nws_f != con_f:
            discrepancies.append({
                'celsius': round(c, 1),
                'nws_f': nws_f,
                'consumer_f': con_f,
                'diff': nws_f - con_f,
                'direction': 'NWS higher' if nws_f > con_f else 'NWS lower'
            })
        c += step
        c = round(c, 1)  # Avoid floating point drift
    return discrepancies


def map_discrepancy_zones(discrepancies: List[Dict]) -> List[Dict]:
    """
    Group consecutive discrepancy points into contiguous zones.
    """
    if not discrepancies:
        return []

    zones = []
    current_zone = {
        'c_start': discrepancies[0]['celsius'],
        'c_end': discrepancies[0]['celsius'],
        'nws_f': discrepancies[0]['nws_f'],
        'consumer_f': discrepancies[0]['consumer_f'],
        'diff': discrepancies[0]['diff'],
        'direction': discrepancies[0]['direction']
    }

    for d in discrepancies[1:]:
        # Continue zone if consecutive and same difference
        if (abs(d['celsius'] - current_zone['c_end'] - 0.1) < 0.05 and
                d['diff'] == current_zone['diff']):
            current_zone['c_end'] = d['celsius']
        else:
            zones.append(current_zone.copy())
            current_zone = {
                'c_start': d['celsius'],
                'c_end': d['celsius'],
                'nws_f': d['nws_f'],
                'consumer_f': d['consumer_f'],
                'diff': d['diff'],
                'direction': d['direction']
            }
    zones.append(current_zone)
    return zones


def get_kalshi_bracket(temp_f: int, bracket_width: int = 2) -> Tuple[int, int]:
    """
    Determine which Kalshi bracket a temperature falls into.
    Kalshi uses 2°F brackets. We assume brackets are aligned on even numbers.
    E.g., 56-57, 58-59, 60-61, etc.
    """
    # Brackets: ..., [56,57], [58,59], [60,61], ...
    bracket_start = (temp_f // bracket_width) * bracket_width
    return (bracket_start, bracket_start + bracket_width - 1)


def is_bracket_crossing(nws_f: int, consumer_f: int, bracket_width: int = 2) -> bool:
    """Check if NWS and consumer readings fall in different Kalshi brackets."""
    return get_kalshi_bracket(nws_f, bracket_width) != get_kalshi_bracket(consumer_f, bracket_width)


if __name__ == '__main__':
    # Quick demo: show all discrepancy zones
    print("=== NWS Standard Rounding vs Consumer App ===\n")
    discs = find_all_discrepancies(
        nws_func=nws_standard_rounding,
        consumer_func=consumer_app_fahrenheit
    )
    zones = map_discrepancy_zones(discs)

    bracket_crossings = 0
    print(f"{'Celsius Range':<18} {'NWS °F':<8} {'Consumer °F':<12} {'Diff':<6} {'Direction':<14} {'Bracket Cross'}")
    print("-" * 80)
    for z in zones:
        crosses = is_bracket_crossing(z['nws_f'], z['consumer_f'])
        if crosses:
            bracket_crossings += 1
        print(f"{z['c_start']:>6.1f} - {z['c_end']:<6.1f}  "
              f"{z['nws_f']:<8} {z['consumer_f']:<12} {z['diff']:>+2}     "
              f"{z['direction']:<14} {'YES' if crosses else 'no'}")

    total_points = int((50.0 - (-20.0)) / 0.1) + 1
    print(f"\nTotal discrepancy points: {len(discs)} / {total_points}")
    print(f"Total discrepancy zones: {len(zones)}")
    print(f"Bracket-crossing zones: {bracket_crossings}")
