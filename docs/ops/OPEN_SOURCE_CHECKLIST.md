# OPEN_SOURCE_CHECKLIST
Date: 2026-03-07
Scope scanned: repo root

## Current status
- `python3 scripts/check_repo_hygiene.py` is the publication gate for tracked high-risk artifacts.
- As of 2026-03-07, the tracked tree contains no `.pem`, `.env`, `.db`, or `jj_state.json` files.
- The same check scans tracked text files for high-confidence secret patterns and currently reports clean.

## What the check blocks
- Tracked `*.pem` files.
- Tracked `.env` files.
- Tracked `*.db` files.
- Tracked `jj_state.json`.
- High-confidence secret material in tracked text files, including private-key headers and live token/key formats.

## Run before public pushes

```bash
python3 scripts/check_repo_hygiene.py
```

Exit code `0` means the tracked repo is clean for this gate. Exit code `1` means a blocked artifact or secret-like pattern was found and must be removed or untracked before pushing.

## Scope notes
- Example and template files such as `.env.example` are allowed.
- Placeholder strings such as `sk-...`, `sk-ant-...`, and `PASTE_...` are ignored so the check does not fail on documentation examples.
- This is a narrow publication gate, not a full redaction audit. Public IPs, emails, and other non-secret identifiers still need manual review when publishing.
