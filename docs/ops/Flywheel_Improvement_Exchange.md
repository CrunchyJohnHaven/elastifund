# Flywheel Improvement Exchange

Status: canonical runbook
Last updated: 2026-03-11
Category: canonical runbook
Canonical: yes
Previous status: implemented MVP (2026-03-07)

## Purpose

The improvement exchange lets one Elastifund fork tell another:

- what change it made
- why it made that change
- whether it improved or failed
- what the latest evidence looked like
- which code files were involved

This is intentionally more structured than a plain bulletin. A peer should not just say "this worked." It should ship an evidence bundle that another fork can verify, inspect, replay locally, and only then consider for paper or shadow deployment.

## Safety Model

The exchange is designed to maximize shared learning without allowing one fork to push unverified code into another fork's live capital stack.

Allowed:

- share code files
- share a patch diff when available
- share positive, negative, or mixed outcomes
- auto-import into a local review queue
- auto-generate a review packet and PR body draft

Not allowed:

- direct live-to-live code application
- automatic promotion to meaningful live capital because a peer said it worked
- bypassing local replay, shadow, or paper verification

## Bundle Contents

Each improvement bundle contains:

- `bundle_id`
- `peer_name`
- `strategy`
- `claim`
- `evidence`
- `code.files`
- `code.patch_diff`
- `integrity.bundle_sha256`
- `integrity.signature_hmac_sha256` when signed

### Claim

The claim captures the peer's interpretation:

- `outcome`: `improved`, `failed`, or `mixed`
- `summary`: short explanation of what changed and what happened
- `hypothesis`: why the peer thought the change was worth trying

### Evidence

The current MVP attaches:

- latest local flywheel snapshot for the strategy version
- latest promotion decision for the strategy version

That gives the receiving fork a machine-readable view of the peer's current status without pretending this is enough to trust the result blindly.

### Code Payload

Bundles include selected source files in plain text and, when available, a git patch diff against `HEAD` or another chosen base ref.

This means a peer can say:

- "here is the exact file content"
- "here is the patch"
- "here is the evidence attached to the change"

## Verification

Import verifies:

1. bundle SHA256 over the canonical unsigned body
2. SHA256 for every attached file
3. optional HMAC signature when a shared secret is provided

Possible verification statuses:

- `verified`
- `signature_unchecked`
- `unsigned`

If a signature is required and missing, import fails. If a signature is present and incorrect, import fails.

## Review Packet

Import writes a local review packet under `reports/flywheel/peer_improvements/<bundle_id>/`:

- `bundle.json`
- `review.md`
- `pr_body.md`
- `patch.diff` when present
- extracted code files under `files/`

This is the handoff package for local replay and bounded adoption.

## CLI

Export:

```bash
python -m data_layer flywheel-export-improvement \
  --db-url sqlite:///data/flywheel_control.db \
  --peer-name elastifund-main \
  --strategy-key polymarket-bot \
  --version-label runtime-live \
  --outcome mixed \
  --summary "Shared runtime wiring and live bridge improvements" \
  --hypothesis "Standardized bridge and evidence exchange should increase iteration speed across forks" \
  --include-path flywheel/bridge.py \
  --include-path flywheel/improvement_exchange.py \
  --include-path data_layer/cli.py \
  --signing-secret "$FLYWHEEL_EXCHANGE_SECRET" \
  --output /tmp/polymarket_runtime_bundle.json
```

Import:

```bash
python -m data_layer flywheel-import-improvement \
  --db-url sqlite:///data/flywheel_control.db \
  --input /tmp/polymarket_runtime_bundle.json \
  --review-dir reports/flywheel/peer_improvements \
  --signing-secret "$FLYWHEEL_EXCHANGE_SECRET"
```

## Adoption Workflow

The receiving fork should follow the same bounded path every time:

1. verify integrity and signature
2. inspect `review.md` and `patch.diff`
3. replay on local data
4. if replay passes, deploy to `paper` or `shadow`
5. only after local evidence clears policy, consider `micro_live`

That is how a network of autonomous companies shares search results without sharing blind trust.
