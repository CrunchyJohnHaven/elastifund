# JJ-N Engine Layer (`nontrading/engines`)

Engine modules represent stage-local behavior inside the revenue pipeline.

## Stage Ownership

- `account_intelligence.py`: account research and enrichment.
- `outreach.py`: outbound message preparation, compliance checks, and approval routing.
- `interaction.py`: response and meeting-stage transitions.
- `proposal.py`: proposal emission and progression.
- `learning.py`: outcome recording and feedback loop.

## Canonical Orchestrator

- `nontrading/pipeline.py` is the canonical runner.
- Engine `process()` compatibility methods remain for narrow callers/tests and should not be treated as a second orchestration framework.
