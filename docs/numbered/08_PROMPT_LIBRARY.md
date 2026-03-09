# 08 Prompt Library
Version: 1.0.0
Date: 2026-03-09
Source: `COMMAND_NODE.md`, `research/platform_vision_document.md`, `CLAUDE.md`, `PROJECT_INSTRUCTIONS.md`, `research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md`
Purpose: Define the canonical prompt families, review process, and prompt-governance rules.
Related docs: `02_ARCHITECTURE.md`, `06_EXPERIMENT_DIARY.md`, `09_GOVERNANCE_AND_SAFETY.md`, `11_PUBLIC_MESSAGING.md`

## Prompt Governance Rule

Prompts are code.
That means prompt changes should be versioned, reviewed, tested, and linked to observed outcomes.
A clever prompt without a measurement trail is just prose.

## Canonical Prompt Families

### Research Prompts

Used to generate new hypotheses, strategy families, and ranking logic.
The current repo includes deep-research prompts such as `research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md`.
These prompts should output hypotheses, scoring logic, failure modes, implementation complexity, and next gating decisions.

### Trading Estimation Prompts

Used by the slower-market predictive lane.
The key rule is anti-anchoring:
do not show the model the market price before it estimates probability.
Prompt changes here should be evaluated against calibration and Brier-style outcomes, not just narrative plausibility.

### Dispatch Prompts

Used to hand focused work to tools or agents.
`COMMAND_NODE.md` defines a standard dispatch template:

- reference the command node
- state the exact task
- list relevant files
- define output format
- define done conditions
- remind the next agent to review for stale docs

### Non-Trading Message Prompts

Used for account research, outreach drafting, meeting briefs, proposal drafting, and follow-up logic.
These prompts must remain policy-governed and should not bypass approval classes during early phases.

## Prompt Review Criteria

Every meaningful prompt change should answer:

- What behavior is expected to improve?
- What failure mode is it trying to reduce?
- Which metric or artifact will show whether it worked?
- Is the change safe for the current autonomy level?

## Known Rules From Current Research

Current source docs emphasize several durable prompt lessons:

- base-rate-first reasoning helps more than elaborate theatrics
- calibration matters more than ornate phrasing
- prompts should preserve temporal grounding
- prompt variants should be compared against evidence, not preference
- harmful prompt styles should be retired once the data says so

## Prompt Storage And Referencing

Prompts should live in durable, discoverable paths, not only inside transient chats.
When a prompt becomes canonical, reference it from the numbered docs and from the workflow docs that use it.
When a prompt is experimental, link it to the experiment that owns it.

## Suggested Prompt Review Process

1. Propose the change and the target outcome.
2. Run the narrowest evaluation that can detect improvement.
3. Store the prompt or diff in version control.
4. Link the change to the metric, test, or report that justified it.
5. Update the relevant doc if the prompt becomes canonical.

## Failure Modes To Avoid

- changing prompts and metrics at the same time without attribution
- keeping effective prompts only in chat history
- describing a prompt as "better" without evidence
- letting non-trading prompts outrun approval policy
- using public messaging language that overclaims capability

## Current Priority Prompt Work

The current repo context suggests three important prompt lanes:

- research prompts that generate better strategy hypotheses
- trading prompts that preserve anti-anchoring and calibration discipline
- JJ-N prompts that support safe account scoring, outreach, and proposal work

Last verified: 2026-03-09 against `COMMAND_NODE.md`, `research/platform_vision_document.md`, and `CLAUDE.md`.
Next review: 2026-06-09.
