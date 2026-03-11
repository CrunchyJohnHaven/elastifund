# Backtest Data Classification

| Class | Files | Source control policy |
|---|---|---|
| Canonical frozen benchmark input | `historical_markets_532.json`, `claude_cache.json` | Tracked and hash-pinned by `benchmarks/calibration_v1/manifest.json` |
| Generated cache and run outputs | `historical_markets.json`, `ensemble_cache.json`, `*_results.json`, `*_analysis.json`, other ad-hoc JSON outputs | Ignored; regenerate from backtest/collector and run scripts |

## Operator Notes

- Keep benchmark inputs stable unless intentionally revving the benchmark manifest.
- Do not commit regenerated caches or run outputs from this directory.
- If `historical_markets.json` is missing, regenerate it via the collector pipeline instead of restoring from git history.
