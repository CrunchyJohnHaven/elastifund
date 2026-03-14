# Leaderboards Routes

| Field | Value |
|---|---|
| Route group | `/leaderboards/` |
| Entry files | `leaderboards/trading/index.html`, `leaderboards/worker/index.html` |
| Status | `active` |
| Purpose | Public evidence boards for trading and worker lanes |
| Shared assets | `/site.css`, `/site.js` |

## Route Taxonomy

- `/leaderboards/trading/`: active trading-proof board.
- `/leaderboards/worker/`: active worker/JJ-N board.

## Naming And Layout Rules

- Keep route entrypoints as `index.html` under each lane subdirectory.
- Keep lane naming stable (`trading`, `worker`) for link compatibility.
- Keep shared styling and runtime data binding in root `/site.css` and `/site.js`.
