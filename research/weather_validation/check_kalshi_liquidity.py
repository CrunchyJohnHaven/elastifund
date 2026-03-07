"""
Check Kalshi weather market liquidity (READ-ONLY).
No orders placed — just market data queries.
"""

import json
import os
import sys
from pathlib import Path

# Try kalshi-python SDK
try:
    from kalshi import KalshiClient
    HAS_KALSHI_SDK = True
except ImportError:
    try:
        import kalshi_python
        from kalshi_python.api import default_api
        HAS_KALSHI_SDK = True
    except ImportError:
        HAS_KALSHI_SDK = False

import requests

# Kalshi API base (production)
KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"

RSA_KEY_PATH = Path(os.environ.get("KALSHI_RSA_KEY_PATH", "kalshi/kalshi_rsa_private.pem"))
API_KEY_ID = os.environ.get("KALSHI_API_KEY_ID", "")


def check_public_weather_markets():
    """
    Try to fetch weather market data from Kalshi's public endpoints.
    Some market listing endpoints may be accessible without auth.
    """
    results = {
        'api_accessible': False,
        'weather_markets_found': 0,
        'market_details': [],
        'errors': [],
    }

    # Try the public events endpoint with weather search
    endpoints_to_try = [
        f"{KALSHI_API_BASE}/events?series_ticker=KXHIGHNY",
        f"{KALSHI_API_BASE}/events?series_ticker=KXHIGHORD",
        f"{KALSHI_API_BASE}/events?series_ticker=KXHIGHAUS",
        f"{KALSHI_API_BASE}/events?with_nested_markets=true&series_ticker=KXHIGH",
        f"{KALSHI_API_BASE}/markets?series_ticker=KXHIGHNY",
        f"{KALSHI_API_BASE}/markets?series_ticker=KXHIGH",
        # Try broader weather search
        f"{KALSHI_API_BASE}/events?status=open&series_ticker=KXTEMP",
        f"{KALSHI_API_BASE}/events?status=open&series_ticker=KXWEATHER",
    ]

    for url in endpoints_to_try:
        try:
            resp = requests.get(url, timeout=10, headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            })
            if resp.status_code == 200:
                results['api_accessible'] = True
                data = resp.json()
                if 'events' in data and data['events']:
                    for event in data['events']:
                        results['weather_markets_found'] += 1
                        results['market_details'].append({
                            'ticker': event.get('event_ticker', ''),
                            'title': event.get('title', ''),
                            'category': event.get('category', ''),
                            'status': event.get('status', ''),
                            'markets': len(event.get('markets', [])),
                        })
                elif 'markets' in data and data['markets']:
                    for market in data['markets']:
                        results['weather_markets_found'] += 1
                        results['market_details'].append({
                            'ticker': market.get('ticker', ''),
                            'title': market.get('title', ''),
                            'status': market.get('status', ''),
                            'yes_bid': market.get('yes_bid', 0),
                            'yes_ask': market.get('yes_ask', 0),
                            'volume': market.get('volume', 0),
                            'open_interest': market.get('open_interest', 0),
                        })
                elif resp.status_code == 200:
                    # API works but no results for this query
                    pass
            else:
                results['errors'].append(f"{url}: HTTP {resp.status_code}")
        except Exception as e:
            results['errors'].append(f"{url}: {str(e)}")

    # Also try to find any weather-related events
    try:
        resp = requests.get(
            f"{KALSHI_API_BASE}/events",
            params={'status': 'open', 'limit': 200},
            timeout=15,
            headers={'Accept': 'application/json'},
        )
        if resp.status_code == 200:
            data = resp.json()
            weather_events = []
            for event in data.get('events', []):
                title = event.get('title', '').lower()
                category = event.get('category', '').lower()
                ticker = event.get('event_ticker', '').upper()
                if any(kw in title for kw in ['temperature', 'weather', 'high temp', 'degrees']):
                    weather_events.append(event)
                elif any(kw in category for kw in ['weather', 'climate', 'temperature']):
                    weather_events.append(event)
                elif 'KXHIGH' in ticker or 'TEMP' in ticker or 'WEATHER' in ticker:
                    weather_events.append(event)

            results['weather_events_from_scan'] = len(weather_events)
            for e in weather_events[:10]:
                results['market_details'].append({
                    'ticker': e.get('event_ticker', ''),
                    'title': e.get('title', ''),
                    'category': e.get('category', ''),
                    'n_markets': len(e.get('markets', [])),
                })
    except Exception as e:
        results['errors'].append(f"Event scan: {str(e)}")

    return results


if __name__ == '__main__':
    print("Checking Kalshi weather market liquidity (READ-ONLY)...")
    print(f"SDK available: {HAS_KALSHI_SDK}")
    print()

    results = check_public_weather_markets()
    print(f"API accessible: {results['api_accessible']}")
    print(f"Weather markets found: {results['weather_markets_found']}")
    print(f"Weather events from scan: {results.get('weather_events_from_scan', 'N/A')}")

    if results['market_details']:
        print("\nMarket details:")
        for m in results['market_details']:
            print(f"  {json.dumps(m, indent=2)}")

    if results['errors']:
        print(f"\nErrors ({len(results['errors'])}):")
        for e in results['errors'][:5]:
            print(f"  {e}")

    # Save results
    with open(Path(__file__).parent / 'kalshi_liquidity.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to kalshi_liquidity.json")
