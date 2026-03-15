"""
Weather Bracket Arbitrage — Full Backtest & Analysis

Uses real ASOS hourly data + IEM daily summaries to:
1. Validate the NWS rounding model against official daily highs
2. Count discrepancies between NWS-protocol and consumer-app readings
3. Identify bracket-crossing trading opportunities
4. Simulate P&L with realistic Kalshi fee structure
5. Run sensitivity analysis across rounding variants
"""

import json
import math
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

import numpy as np

from rounding_model import (
    nws_standard_rounding,
    nws_bankers_rounding,
    nws_truncation,
    nws_metar_integer,
    consumer_app_fahrenheit,
    consumer_app_bankers,
    find_all_discrepancies,
    map_discrepancy_zones,
    get_kalshi_bracket,
    is_bracket_crossing,
)

BASE_DIR = Path(__file__).parent
RAW_ASOS_DIR = BASE_DIR / "raw_asos"
NWS_DAILY_DIR = BASE_DIR / "nws_daily"

STATIONS = ['NYC', 'ORD', 'AUS']
STATION_NAMES = {
    'NYC': 'Central Park, NYC (KNYC)',
    'ORD': 'Chicago O\'Hare (KORD)',
    'AUS': 'Austin Bergstrom (KAUS)',
}


def load_data(station: str) -> Tuple[Dict, Dict]:
    """Load daily max from hourly and official daily summaries."""
    hourly_max_path = RAW_ASOS_DIR / f"{station}_daily_max.json"
    daily_path = NWS_DAILY_DIR / f"{station}_daily.json"

    hourly_max = {}
    if hourly_max_path.exists():
        with open(hourly_max_path) as f:
            hourly_max = json.load(f)

    daily_official = {}
    if daily_path.exists():
        with open(daily_path) as f:
            daily_list = json.load(f)
            for r in daily_list:
                daily_official[r['day']] = r['max_tmpf']

    return hourly_max, daily_official


def validate_rounding_model(station: str, hourly_max: Dict, daily_official: Dict) -> Dict:
    """
    Compare our rounding model predictions against official daily highs.
    This tells us WHICH rounding protocol the NWS actually uses.
    """
    results = {
        'standard': {'matches': 0, 'misses': 0, 'errors': []},
        'bankers': {'matches': 0, 'misses': 0, 'errors': []},
        'truncation': {'matches': 0, 'misses': 0, 'errors': []},
        'metar_int': {'matches': 0, 'misses': 0, 'errors': []},
        'direct_reported': {'matches': 0, 'misses': 0, 'errors': []},
    }

    common_dates = set(hourly_max.keys()) & set(daily_official.keys())

    for date in sorted(common_dates):
        raw_c = hourly_max[date]['max_tmpc']
        official_f = int(daily_official[date])

        # The ASOS already reports tmpf — check if official matches ASOS report directly
        asos_reported_f = int(hourly_max[date]['max_tmpf'])

        predictions = {
            'standard': nws_standard_rounding(raw_c),
            'bankers': nws_bankers_rounding(raw_c),
            'truncation': nws_truncation(raw_c),
            'metar_int': nws_metar_integer(round(raw_c)),  # METAR gives integer C
            'direct_reported': asos_reported_f,
        }

        for model_name, pred_f in predictions.items():
            if pred_f == official_f:
                results[model_name]['matches'] += 1
            else:
                results[model_name]['misses'] += 1
                results[model_name]['errors'].append({
                    'date': date,
                    'raw_c': raw_c,
                    'predicted_f': pred_f,
                    'official_f': official_f,
                    'error': pred_f - official_f,
                })

    total = len(common_dates)
    for model_name in results:
        if total > 0:
            results[model_name]['accuracy'] = results[model_name]['matches'] / total
            results[model_name]['total'] = total

    return results


def run_discrepancy_backtest(station: str, hourly_max: Dict, daily_official: Dict) -> Dict:
    """
    For each day, compare NWS-protocol reading vs consumer-app reading.
    Identify bracket crossings that would be tradeable.
    """
    days_data = []
    common_dates = set(hourly_max.keys()) & set(daily_official.keys())

    for date in sorted(common_dates):
        raw_c = hourly_max[date]['max_tmpc']
        official_f = int(daily_official[date])

        # NWS protocol: round C first, then convert
        # Use METAR integer model since METAR reports integer C
        nws_f = nws_metar_integer(round(raw_c))

        # Consumer app: direct conversion
        consumer_f = consumer_app_fahrenheit(raw_c)

        discrepancy = nws_f != consumer_f
        nws_bracket = get_kalshi_bracket(nws_f)
        consumer_bracket = get_kalshi_bracket(consumer_f)
        bracket_cross = nws_bracket != consumer_bracket

        # Also check: does ACTUAL official match NWS model or consumer model?
        official_matches_nws = (official_f == nws_f)
        official_matches_consumer = (official_f == consumer_f)

        days_data.append({
            'date': date,
            'raw_c': raw_c,
            'metar_c_int': round(raw_c),
            'nws_f': nws_f,
            'consumer_f': consumer_f,
            'official_f': official_f,
            'discrepancy': discrepancy,
            'bracket_cross': bracket_cross,
            'nws_bracket': nws_bracket,
            'consumer_bracket': consumer_bracket,
            'official_matches_nws': official_matches_nws,
            'official_matches_consumer': official_matches_consumer,
        })

    # Summary stats
    total_days = len(days_data)
    disc_days = sum(1 for d in days_data if d['discrepancy'])
    bracket_cross_days = sum(1 for d in days_data if d['bracket_cross'])
    nws_correct = sum(1 for d in days_data if d['official_matches_nws'])
    consumer_correct = sum(1 for d in days_data if d['official_matches_consumer'])

    return {
        'days': days_data,
        'total_days': total_days,
        'discrepancy_days': disc_days,
        'discrepancy_rate': disc_days / total_days if total_days > 0 else 0,
        'bracket_crossing_days': bracket_cross_days,
        'bracket_crossing_rate': bracket_cross_days / total_days if total_days > 0 else 0,
        'nws_model_accuracy': nws_correct / total_days if total_days > 0 else 0,
        'consumer_model_accuracy': consumer_correct / total_days if total_days > 0 else 0,
    }


def check_predictability(station: str) -> Dict:
    """
    Check if we can predict the daily max bracket >2 hours before market close.
    This requires checking afternoon ASOS readings to see if the daily max
    is already established by early afternoon.

    ASOS reports hourly. For most cities, the daily high occurs between 12-4pm local.
    If by 2pm local the max so far is already in a discrepancy zone, we can trade early.
    """
    import csv
    from io import StringIO
    from datetime import datetime

    asos_path = RAW_ASOS_DIR / f"{station}_asos.csv"
    if not asos_path.exists():
        return {'predictable': 'unknown', 'reason': 'no hourly data'}

    with open(asos_path) as f:
        raw_text = f.read()

    lines = raw_text.strip().split('\n')
    data_lines = [l for l in lines if not l.startswith('#')]
    if not data_lines:
        return {'predictable': 'unknown', 'reason': 'empty data'}

    reader = csv.DictReader(StringIO('\n'.join(data_lines)))
    daily_readings = defaultdict(list)

    for row in reader:
        try:
            tmpc = row.get('tmpc', 'M')
            if tmpc == 'M':
                continue
            valid = row['valid']
            date_str = valid[:10]
            hour = int(valid[11:13])
            daily_readings[date_str].append({
                'hour_utc': hour,
                'tmpc': float(tmpc),
            })
        except (ValueError, KeyError):
            continue

    # For each day, check if the max by 18:00 UTC (~1-2pm EST/CST/CST)
    # was already the final daily max
    early_correct = 0
    total_checked = 0

    for date_str, readings in daily_readings.items():
        if len(readings) < 10:
            continue
        total_checked += 1

        all_max = max(r['tmpc'] for r in readings)
        early_readings = [r for r in readings if r['hour_utc'] <= 20]  # By 8pm UTC = 2-3pm local
        if early_readings:
            early_max = max(r['tmpc'] for r in early_readings)
            # Check if early max rounds to same integer Celsius as final max
            if round(early_max) == round(all_max):
                early_correct += 1

    return {
        'total_days_checked': total_checked,
        'early_prediction_correct': early_correct,
        'early_prediction_rate': early_correct / total_checked if total_checked > 0 else 0,
    }


def simulate_trading_pnl(backtest_results: Dict, bankroll: float = 100.0) -> Dict:
    """
    Simulate P&L for bracket-crossing trading opportunities.

    Strategy: When we detect a discrepancy where the NWS will read differently
    from consumer apps, buy the NWS-correct bracket at longshot prices.

    Key assumptions documented:
    - Entry price: $0.05-$0.15 for the correct bracket (it's priced as unlikely)
    - Win rate: depends on NWS model accuracy
    - Kalshi taker fee: 7% coefficient × price × (1 - price)
    - Position size: $5 per trade (5% of $100 bankroll)
    """
    trades = []
    daily_returns = []

    for day in backtest_results['days']:
        if not day['bracket_cross']:
            continue

        # Can only trade if we're confident NWS model is right
        if not day['official_matches_nws']:
            # In live trading, we wouldn't know this. But for backtest,
            # we check if our model would have been right.
            trades.append({
                'date': day['date'],
                'entry_price': 0.10,
                'outcome': 'loss',
                'pnl': -5.0,  # Lost the position
                'fee': kalshi_taker_fee(0.10, 5.0),
            })
            daily_returns.append(-5.0 / bankroll)
            continue

        # Our model correctly predicts NWS official reading
        # Assume we buy the correct bracket at longshot price
        # Entry price assumption: bracket is priced ~$0.10 because market
        # prices the consumer-app bracket as the favorite
        entry_price = 0.10  # $0.10 per contract (10 cents on the dollar)
        position_size_usd = 5.0  # $5 per trade
        n_contracts = position_size_usd / entry_price  # 50 contracts at $0.10

        # Win: each contract pays $1.00 - entry_price = $0.90 profit
        gross_profit = n_contracts * (1.00 - entry_price)

        # Kalshi fees
        entry_fee = kalshi_taker_fee(entry_price, n_contracts)
        # On settlement, no exit fee (contract settles, not sold)

        net_profit = gross_profit - entry_fee

        trades.append({
            'date': day['date'],
            'entry_price': entry_price,
            'n_contracts': n_contracts,
            'gross_profit': gross_profit,
            'fee': entry_fee,
            'net_profit': net_profit,
            'outcome': 'win',
        })
        daily_returns.append(net_profit / bankroll)

    # Non-trading days get 0 return
    total_trading_days = backtest_results['total_days']
    non_trade_days = total_trading_days - len(trades)
    daily_returns.extend([0.0] * non_trade_days)

    # Calculate stats
    total_pnl = sum(t.get('net_profit', t.get('pnl', 0)) for t in trades)
    wins = sum(1 for t in trades if t['outcome'] == 'win')
    losses = sum(1 for t in trades if t['outcome'] == 'loss')
    total_fees = sum(t['fee'] for t in trades)

    # Annualize
    days_in_period = max(backtest_results['total_days'], 1)
    annualization_factor = 365.0 / days_in_period
    arr = (total_pnl / bankroll) * annualization_factor * 100  # as percentage

    # Sharpe ratio (annualized)
    if daily_returns and np.std(daily_returns) > 0:
        sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(365)
    else:
        sharpe = 0.0

    # Max risk on single day
    max_risk = max(abs(t.get('pnl', -t.get('net_profit', 0))) for t in trades) if trades else 0

    return {
        'trades': trades,
        'total_trades': len(trades),
        'wins': wins,
        'losses': losses,
        'win_rate': wins / len(trades) if trades else 0,
        'total_pnl': total_pnl,
        'total_fees': total_fees,
        'avg_profit_per_trade': total_pnl / len(trades) if trades else 0,
        'arr_pct': arr,
        'sharpe_ratio': sharpe,
        'max_single_day_risk': 5.0,  # Fixed $5 position size
        'bankroll': bankroll,
    }


def kalshi_taker_fee(price: float, n_contracts: float) -> float:
    """
    Kalshi taker fee: 7% coefficient × price × (1 - price) × n_contracts
    Capped at $0.07 per contract.
    """
    per_contract = min(0.07 * price * (1.0 - price), 0.07)
    return per_contract * n_contracts


def sensitivity_analysis() -> Dict:
    """Run sensitivity across rounding model variants and bracket widths."""
    results = {}

    # Test all rounding model combinations
    nws_models = {
        'standard': nws_standard_rounding,
        'bankers': nws_bankers_rounding,
        'truncation': nws_truncation,
    }
    consumer_models = {
        'standard': consumer_app_fahrenheit,
        'bankers': consumer_app_bankers,
    }

    for nws_name, nws_func in nws_models.items():
        for con_name, con_func in consumer_models.items():
            key = f"nws_{nws_name}_vs_consumer_{con_name}"
            discs = find_all_discrepancies(
                c_min=-10, c_max=45,  # Realistic range for target cities
                nws_func=nws_func,
                consumer_func=con_func,
            )
            zones = map_discrepancy_zones(discs)
            bracket_crosses = sum(1 for z in zones
                                  if is_bracket_crossing(z['nws_f'], z['consumer_f']))
            results[key] = {
                'discrepancy_points': len(discs),
                'discrepancy_zones': len(zones),
                'bracket_crossing_zones': bracket_crosses,
            }

    # Bracket width sensitivity
    for width in [1, 2, 3, 4, 5]:
        discs = find_all_discrepancies(c_min=-10, c_max=45)
        zones = map_discrepancy_zones(discs)
        crosses = sum(1 for z in zones
                      if get_kalshi_bracket(z['nws_f'], width) !=
                      get_kalshi_bracket(z['consumer_f'], width))
        results[f'bracket_width_{width}'] = {
            'bracket_crossing_zones': crosses,
            'total_zones': len(zones),
        }

    # Seasonal analysis - which temp ranges have most discrepancies
    seasonal = {
        'winter (-10 to 5C / 14-41F)': find_all_discrepancies(c_min=-10, c_max=5),
        'spring/fall (5 to 20C / 41-68F)': find_all_discrepancies(c_min=5, c_max=20),
        'summer (20 to 40C / 68-104F)': find_all_discrepancies(c_min=20, c_max=40),
    }
    for season, discs in seasonal.items():
        total_pts = int((discs[-1]['celsius'] - discs[0]['celsius']) / 0.1) + 1 if discs else 0
        results[f'season: {season}'] = {
            'discrepancy_points': len(discs),
            'rate': f"{len(discs)/max(total_pts,1)*100:.1f}% of range",
        }

    return results


def run_full_analysis():
    """Run everything and return structured results for report generation."""
    print("=" * 60)
    print("WEATHER BRACKET ARBITRAGE — FULL VALIDATION")
    print("=" * 60)

    all_results = {
        'stations': {},
        'combined': {
            'total_days': 0,
            'total_discrepancies': 0,
            'total_bracket_crossings': 0,
            'total_trades': 0,
            'total_pnl': 0,
        },
    }

    for station in STATIONS:
        print(f"\n{'='*40}")
        print(f"Station: {STATION_NAMES[station]}")
        print(f"{'='*40}")

        hourly_max, daily_official = load_data(station)
        print(f"  Hourly daily max records: {len(hourly_max)}")
        print(f"  Official daily records: {len(daily_official)}")

        # Step 1: Validate rounding models
        print("\n  --- Rounding Model Validation ---")
        validation = validate_rounding_model(station, hourly_max, daily_official)
        for model, v in validation.items():
            acc = v.get('accuracy', 0)
            total = v.get('total', 0)
            print(f"  {model:20s}: {v['matches']}/{total} = {acc*100:.1f}% accuracy")

        # Step 2: Run discrepancy backtest
        print("\n  --- Discrepancy Backtest ---")
        backtest = run_discrepancy_backtest(station, hourly_max, daily_official)
        print(f"  Total days: {backtest['total_days']}")
        print(f"  Discrepancy days: {backtest['discrepancy_days']} ({backtest['discrepancy_rate']*100:.1f}%)")
        print(f"  Bracket crossing days: {backtest['bracket_crossing_days']} ({backtest['bracket_crossing_rate']*100:.1f}%)")
        print(f"  NWS model accuracy: {backtest['nws_model_accuracy']*100:.1f}%")
        print(f"  Consumer model accuracy: {backtest['consumer_model_accuracy']*100:.1f}%")

        # Step 3: Check predictability
        print("\n  --- Predictability (by 2pm local) ---")
        predictability = check_predictability(station)
        if 'early_prediction_rate' in predictability:
            print(f"  Days checked: {predictability['total_days_checked']}")
            print(f"  Max temp settled by 2pm: {predictability['early_prediction_rate']*100:.1f}%")

        # Step 4: Simulate P&L
        print("\n  --- Simulated P&L ---")
        pnl = simulate_trading_pnl(backtest)
        print(f"  Total trades: {pnl['total_trades']}")
        print(f"  Wins: {pnl['wins']}, Losses: {pnl['losses']}")
        print(f"  Win rate: {pnl['win_rate']*100:.1f}%")
        print(f"  Total P&L: ${pnl['total_pnl']:.2f}")
        print(f"  Total fees: ${pnl['total_fees']:.2f}")
        print(f"  Avg profit/trade: ${pnl['avg_profit_per_trade']:.2f}")
        print(f"  ARR: {pnl['arr_pct']:.1f}%")
        print(f"  Sharpe: {pnl['sharpe_ratio']:.2f}")

        # Show bracket crossing details
        if backtest['bracket_crossing_days'] > 0:
            print("\n  --- Bracket Crossing Details ---")
            for day in backtest['days']:
                if day['bracket_cross']:
                    print(f"    {day['date']}: raw={day['raw_c']:.1f}°C, "
                          f"NWS={day['nws_f']}°F [{day['nws_bracket']}], "
                          f"Consumer={day['consumer_f']}°F [{day['consumer_bracket']}], "
                          f"Official={day['official_f']}°F, "
                          f"NWS_correct={'YES' if day['official_matches_nws'] else 'NO'}")

        all_results['stations'][station] = {
            'validation': {k: {kk: vv for kk, vv in v.items() if kk != 'errors'}
                           for k, v in validation.items()},
            'backtest': {k: v for k, v in backtest.items() if k != 'days'},
            'predictability': predictability,
            'pnl': {k: v for k, v in pnl.items() if k != 'trades'},
            'bracket_crossing_details': [d for d in backtest['days'] if d['bracket_cross']],
        }
        all_results['combined']['total_days'] += backtest['total_days']
        all_results['combined']['total_discrepancies'] += backtest['discrepancy_days']
        all_results['combined']['total_bracket_crossings'] += backtest['bracket_crossing_days']
        all_results['combined']['total_trades'] += pnl['total_trades']
        all_results['combined']['total_pnl'] += pnl['total_pnl']

    # Combined P&L metrics
    combined = all_results['combined']
    combined['discrepancy_rate'] = (combined['total_discrepancies'] /
                                     combined['total_days'] * 100
                                     if combined['total_days'] > 0 else 0)
    combined['bracket_crossing_rate'] = (combined['total_bracket_crossings'] /
                                          combined['total_days'] * 100
                                          if combined['total_days'] > 0 else 0)
    combined['arr_pct'] = (combined['total_pnl'] / 100.0) * (365.0 / max(combined['total_days'] / 3, 1)) * 100

    # Sensitivity analysis
    print(f"\n{'='*40}")
    print("SENSITIVITY ANALYSIS")
    print(f"{'='*40}")
    sensitivity = sensitivity_analysis()
    for key, val in sensitivity.items():
        print(f"  {key}: {val}")
    all_results['sensitivity'] = sensitivity

    # Discrepancy zone table
    print(f"\n{'='*40}")
    print("DISCREPANCY ZONES (Relevant Temperature Ranges)")
    print(f"{'='*40}")
    discs = find_all_discrepancies(c_min=-10, c_max=45)
    zones = map_discrepancy_zones(discs)
    for z in zones:
        crosses = is_bracket_crossing(z['nws_f'], z['consumer_f'])
        if crosses:
            print(f"  {z['c_start']:>5.1f} - {z['c_end']:<5.1f}°C  "
                  f"NWS:{z['nws_f']}°F  Consumer:{z['consumer_f']}°F  "
                  f"diff:{z['diff']:+d}  BRACKET CROSSING")
    all_results['discrepancy_zones'] = zones

    return all_results


if __name__ == '__main__':
    results = run_full_analysis()
    # Save full results
    with open(BASE_DIR / 'backtest_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {BASE_DIR / 'backtest_results.json'}")
