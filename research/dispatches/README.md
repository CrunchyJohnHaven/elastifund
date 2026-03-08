# Research Dispatch System

This directory holds dispatch-ready prompts and briefs for pushing work into the right tool with minimal context thrash.

## What A Dispatch Is

A dispatch is a self-contained task packet that tells one tool or one agent:

- what the task is
- which context it needs
- what “done” looks like
- where the result should land in the repo

## Tool Tags

Each prompt file is tagged with the tool it is meant for:

- `CLAUDE_CODE` -> implementation and repo surgery
- `CLAUDE_DEEP_RESEARCH` -> deep literature and competitive research
- `CHATGPT_DEEP_RESEARCH` -> browsing-heavy empirical research
- `COWORK` -> collaborative analysis and planning
- `GROK` -> real-time market or competitive intel

## Status Flow

Update the file header as work progresses:

`READY -> DISPATCHED -> COMPLETED -> INTEGRATED`

## Priority Levels

- `P0` -> do immediately
- `P1` -> this week
- `P2` -> while P0/P1 are already running
- `P3` -> background / longer-term

## Parallel-Agent Rule

This directory is a natural coordination surface when Codex and Claude Code are working together.

Recommended split:

- Claude Code or a human coordinator selects or writes the dispatch packet
- Codex owns the narrow implementation lane that follows from it
- the closing agent updates docs, tests, and status after verification

Use [docs/PARALLEL_AGENT_WORKFLOW.md](../../docs/PARALLEL_AGENT_WORKFLOW.md) for the actual handoff contract.

## Standard Operating Procedure

All new research should trigger a document sync check. If new evidence changes the repo’s public story, update the affected docs rather than leaving the insight stranded in one prompt output.

## Task Index

Treat the prompt files in this directory as the live task inventory. They are intentionally append-friendly and should stay easy to scan.
