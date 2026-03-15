# Unexecuted Deep Research Prompts

Canonical lane for external-research prompts that have NOT yet been dispatched.

## Purpose

These prompts are designed to be handed to deep-research tools (ChatGPT Deep Research,
Claude Deep Research, Grok, Perplexity, etc.) as self-contained packets. They are NOT
implementation dispatches and should never be mixed with dispatched code tasks.

## Status Flow

Each prompt file uses YAML frontmatter with a `status` field:

- `READY` — written, reviewed, awaiting dispatch
- `DISPATCHED` — sent to a research tool, awaiting results
- `COMPLETED` — results received and saved
- `INTEGRATED` — results absorbed into repo code/docs

## Naming Convention

`BTC5_DRP_NNN_short_slug.md` where NNN is a zero-padded sequence number.

## Current Inventory

Run `scripts/validate_deep_research_prompts.py` for machine-readable status.

## Rules

1. Each prompt must specify: formulas, measurable hypotheses, failure modes, repo integration targets.
2. Prompts are research-only. No runtime mutation.
3. Results land in `research/deep_research_packets/` or `research/dispatches/` as appropriate.
