"""
Fetch historical ASOS METAR data and NWS daily climate summaries.
Falls back to synthetic data if APIs are unreachable.
"""

import os
import requests
import csv
import json
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

BASE_DIR = Path(__file__).parent
RAW_ASOS_DIR = BASE_DIR / "raw_asos"
NWS_DAILY_DIR = BASE_DIR / "nws_daily"

# IEM uses 3-letter codes
STATIONS = {
    'NYC': {'name': 'Central Park, NYC', 'iem': 'NYC', 'ghcnd': 'USW00094728'},
    'ORD': {'name': 'Chicago O\'Hare', 'iem': 'ORD', 'ghcnd': 'USW00094846'},
    'AUS': {'name': 'Austin Bergstrom', 'iem': 'AUS', 'ghcnd': 'USW00013904'},
}


def fetch_iem_asos(station_code: str, start_date: str, end_date: str) -> str | None:
    """
    Fetch hourly ASOS data from Iowa Environmental Mesonet.
    Returns CSV string or None on failure.
    """
    url = (
        f"https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"
        f"station={station_code}&data=tmpf&data=tmpc"
        f"&year1={start_date[:4]}&month1={start_date[5:7]}&day1={start_date[8:10]}"
        f"&year2={end_date[:4]}&month2={end_date[5:7]}&day2={end_date[8:10]}"
        f"&tz=Etc/UTC&format=comma&latlon=no&elev=no"
        f"&missing=M&trace=T&direct=no&report_type=3"
    )
    try:
        print(f"  Fetching IEM ASOS for {station_code}...")
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200 and 'station' in resp.text[:1000]:
            return resp.text
        else:
            print(f"  IEM returned status {resp.status_code} or unexpected content")
            return None
    except Exception as e:
        print(f"  IEM fetch failed: {e}")
        return None


def fetch_iem_daily(station_code: str, network: str, start_date: str, end_date: str) -> str | None:
    """
    Fetch daily summaries from IEM.
    """
    url = (
        f"https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?"
        f"network={network}&stations={station_code}"
        f"&year1={start_date[:4]}&month1={start_date[5:7]}&day1={start_date[8:10]}"
        f"&year2={end_date[:4]}&month2={end_date[5:7]}&day2={end_date[8:10]}"
    )
    try:
        print(f"  Fetching IEM daily for {station_code}...")
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200 and len(resp.text) > 100:
            return resp.text
        else:
            print(f"  IEM daily returned status {resp.status_code}")
            return None
    except Exception as e:
        print(f"  IEM daily fetch failed: {e}")
        return None


def parse_asos_csv(csv_text: str) -> list[dict]:
    """Parse IEM ASOS CSV into list of dicts with cleaned temp values."""
    records = []
    lines = csv_text.strip().split('\n')
    # Skip comment lines starting with #
    data_lines = [l for l in lines if not l.startswith('#')]
    if not data_lines:
        return records

    reader = csv.DictReader(StringIO('\n'.join(data_lines)))
    for row in reader:
        try:
            tmpf = row.get('tmpf', 'M')
            tmpc = row.get('tmpc', 'M')
            if tmpf == 'M' or tmpc == 'M':
                continue
            records.append({
                'station': row['station'],
                'valid': row['valid'],
                'tmpf': float(tmpf),
                'tmpc': float(tmpc),
            })
        except (ValueError, KeyError):
            continue
    return records


def parse_daily_csv(csv_text: str) -> list[dict]:
    """Parse IEM daily summary CSV."""
    records = []
    lines = csv_text.strip().split('\n')
    data_lines = [l for l in lines if not l.startswith('#')]
    if not data_lines:
        return records

    reader = csv.DictReader(StringIO('\n'.join(data_lines)))
    for row in reader:
        try:
            # IEM uses 'max_temp_f' in daily summaries
            max_tmpf = row.get('max_temp_f', row.get('max_tmpf', ''))
            if not max_tmpf or max_tmpf == 'None' or max_tmpf == 'M':
                continue
            records.append({
                'station': row.get('station', ''),
                'day': row.get('day', ''),
                'max_tmpf': float(max_tmpf),
            })
        except (ValueError, KeyError):
            continue
    return records


def compute_daily_max_from_hourly(hourly_records: list[dict]) -> dict[str, dict]:
    """
    From hourly ASOS records, compute daily max temperature.
    Returns {date_str: {max_tmpf, max_tmpc, max_tmpc_raw (the raw C that produced the day's max)}}.
    """
    from collections import defaultdict
    daily = defaultdict(lambda: {'max_tmpf': -999, 'max_tmpc': -999, 'readings': []})

    for r in hourly_records:
        # Parse date from valid timestamp
        date_str = r['valid'][:10]  # YYYY-MM-DD
        daily[date_str]['readings'].append(r)
        if r['tmpc'] > daily[date_str]['max_tmpc']:
            daily[date_str]['max_tmpc'] = r['tmpc']
            daily[date_str]['max_tmpf'] = r['tmpf']

    result = {}
    for date_str, data in sorted(daily.items()):
        if data['max_tmpc'] > -999:
            result[date_str] = {
                'max_tmpf': data['max_tmpf'],
                'max_tmpc': data['max_tmpc'],
                'n_readings': len(data['readings']),
            }
    return result


def save_data(data, filepath: Path):
    """Save data as JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  Saved: {filepath}")


def fetch_all_stations(start_date: str = '2025-12-01', end_date: str = '2026-03-07'):
    """Fetch data for all stations. Returns dict of results."""
    networks = {'NYC': 'NY_ASOS', 'ORD': 'IL_ASOS', 'AUS': 'TX_ASOS'}
    results = {}

    for code, info in STATIONS.items():
        print(f"\n--- {info['name']} ({code}) ---")

        # Fetch hourly ASOS
        asos_csv = fetch_iem_asos(code, start_date, end_date)
        hourly_records = []
        daily_max = {}
        if asos_csv:
            hourly_records = parse_asos_csv(asos_csv)
            print(f"  Got {len(hourly_records)} hourly ASOS records")
            # Save raw CSV
            with open(RAW_ASOS_DIR / f"{code}_asos.csv", 'w') as f:
                f.write(asos_csv)
            # Compute daily max from hourly
            daily_max = compute_daily_max_from_hourly(hourly_records)
            save_data(daily_max, RAW_ASOS_DIR / f"{code}_daily_max.json")
        else:
            print(f"  ASOS fetch failed for {code}")

        # Fetch daily summaries (for official daily high)
        daily_csv = fetch_iem_daily(code, networks[code], start_date, end_date)
        daily_official = []
        if daily_csv:
            daily_official = parse_daily_csv(daily_csv)
            print(f"  Got {len(daily_official)} daily summary records")
            with open(NWS_DAILY_DIR / f"{code}_daily.csv", 'w') as f:
                f.write(daily_csv)
            save_data(daily_official, NWS_DAILY_DIR / f"{code}_daily.json")
        else:
            print(f"  Daily summary fetch failed for {code}")

        results[code] = {
            'hourly_count': len(hourly_records),
            'daily_max': daily_max,
            'daily_official': {r['day']: r['max_tmpf'] for r in daily_official},
            'has_real_data': len(hourly_records) > 0,
        }

    return results


if __name__ == '__main__':
    results = fetch_all_stations()
    for code, r in results.items():
        print(f"\n{code}: {r['hourly_count']} hourly, "
              f"{len(r['daily_max'])} days from hourly, "
              f"{len(r['daily_official'])} days from daily summary")
