# Dispatch Instructions — March 7, 2026
Paste these into Claude Code and Codex instances. Each instance gets ONE task block.

---

## INSTANCE 1: CREDENTIAL AUDIT + REPO PUBLIC PREP (Claude Code)

Paste this:

```
You are working on the Elastifund repo. Read CLAUDE.md first.

TASK: Audit the entire repo for leaked credentials before we make it public. This is blocking everything else.

Step 1: Search every file for anything that looks like a secret:
- Private keys (0x... strings longer than 20 chars)
- API keys, tokens, passphrases
- Wallet addresses that should be private (the proxy wallet in ProjectInstructions.md is intentionally public)
- .pem file contents
- Hardcoded passwords or secrets in Python files
- Any .env files that aren't .env.example

Step 2: Check .gitignore covers:
- .env
- *.pem
- data/*.db (runtime databases with wallet scores)
- Any __pycache__ or .pyc
- node_modules if any exist
- bot/kalshi/kalshi_rsa_private.pem specifically

Step 3: Check git history for leaked secrets:
- Run: git log --all --diff-filter=A -- '*.env' '*.pem' '*.key'
- If any secrets were ever committed, we need to either rewrite history or rotate the keys. Flag what you find.

Step 4: Verify .env.example exists and has placeholder values (not real keys) for every env var the system needs. The current list should include:
- POLY_PRIVATE_KEY
- POLY_SAFE_ADDRESS
- POLY_BUILDER_API_KEY / SECRET / PASSPHRASE
- ANTHROPIC_API_KEY
- OPENAI_API_KEY
- GROQ_API_KEY
- TELEGRAM_BOT_TOKEN / CHAT_ID
- KALSHI_API_KEY_ID (the one in ProjectInstructions.md was scrubbed, verify)

Step 5: Write a report of everything you found. Fix anything fixable (add to .gitignore, replace hardcoded values with os.environ.get() calls). Flag anything that needs key rotation.

Do not push anything. Just prepare the fixes and report what you did.
```

---

## INSTANCE 2: ROOT CONTEXT REFRESH (Claude Code or Codex)

Paste this:

```
You are working on the Elastifund repo. Read CLAUDE.md first — you are JJ.

TASK: Refresh `ProjectInstructions.md` and `docs/REPO_MAP.md` to reflect all changes made today. Together they are the lightweight context package pasted into new AI coding sessions. They need to stay current and compact.

Read these files first:
- CLAUDE.md (new — JJ persona, prime directive, autonomous execution mandate)
- FLYWHEEL_STRATEGY.md (rewritten — 6-phase flywheel, website vision, dual mission)
- README.md (rewritten — agent-run framing, research engine positioning, honest failures section)
- research/edge_backlog_ranked.md (restructured — 6 deployed, 5 building, 10 rejected, 30 pipeline)
- ProjectInstructions.md (credential scrubbed, priority queue)
- research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md (new — 100-strategy prompt with composite scoring)
- research/RTDS_MAKER_EDGE_IMPLEMENTATION.md (new — WebSocket + maker order strategy spec)
- research/LatencyEdgeResearch.md (new — Dublin latency analysis, RTDS feed discovery)
- FastTradeEdgeAnalysis.md (current pipeline output)

Then make sure the refreshed docs include:
1. The JJ persona description (brief — 3 sentences)
2. The prime directive ("John shares info, JJ decides")
3. The dual mission (trading returns + world's best agentic trading resource)
4. The flywheel process (6 phases, 3-5 day cycles)
5. Current strategy status table (6 deployed, 5 building, 10 rejected, 30 pipeline)
6. The RTDS maker edge as a new research finding (summarize in 1 paragraph)
7. The latency finding (Dublin is 5-10ms from CLOB in London, not US)
8. Updated document hierarchy table
9. The open-source guardrails (what's public, what stays in .env)
10. The website vision (1 paragraph summary)

Bump the relevant version/date markers. Keep both files lean enough to fit comfortably into context windows.

Do not rewrite everything. Surgically update the sections that changed. Preserve anything still accurate. Cut anything stale or redundant, especially dead `COMMAND_NODE` references.
```

---

## INSTANCE 3: FIRST THREE DIARY ENTRIES (Codex or Claude Code)

Paste this:

```
You are working on the Elastifund repo. Read CLAUDE.md and FLYWHEEL_STRATEGY.md first.

TASK: Write the first 3 diary entries for the Elastifund research diary. These are the seed content for the website. They tell the story of how we got here.

Create a new directory: docs/diary/

Write these three files:

FILE 1: docs/diary/2026-03-05-calibration-discovery.md
Title: "Day 1: Our AI Was Overconfident — Here's How We Fixed It"
Tell the story of discovering that Claude's raw probability estimates are systematically overconfident (says 90% when reality is ~71%), and how we implemented Platt scaling to fix it. This was the first real insight of the project. Include the actual Platt parameters (A=0.5914, B=-0.3977) and explain what they mean in plain English. A reader with no statistics background should understand why this matters. End with the lesson: "The AI is useful not because it's right, but because its errors are predictable and correctable."

FILE 2: docs/diary/2026-03-06-twelve-strategies-rejected.md
Title: "Day 2: We Tested 12 Strategies. All Failed. That's the Point."
Tell the story of running 12 strategy families through the edge discovery pipeline and getting REJECT ALL. Explain what the kill rules are (minimum signal count, positive post-cost EV, calibration stability, regime decay). Explain why "no edge found" is a real finding, not a failure. List all 12 rejected strategies with one-sentence kill reasons. The key insight: "Most trading edges don't exist. The valuable skill is rejecting bad ideas fast, not finding good ones."

FILE 3: docs/diary/2026-03-07-the-flywheel.md
Title: "Day 3: Building the Machine That Builds the Machine"
Tell the story of today — setting up the flywheel process, writing the Deep Research prompt for 100 new strategies, creating the JJ persona, rewriting all the top-level documentation, and preparing the repo to go public. This is the meta-entry: we're not just trading, we're building a systematic research engine and documenting it openly. Explain the flywheel in plain English. End with: "The trading is the laboratory. The research is the product."

FORMATTING for all three:
- Use the diary template from FLYWHEEL_STRATEGY.md (Day N, What We Did, Strategy Updates, Key Numbers, What We Learned, Tomorrow's Plan)
- Write for a general audience. No jargon without explanation.
- Keep each entry under 500 words. Dense, no filler.
- Include actual numbers from the codebase (532 markets, 71.2% win rate, 12 rejected strategies, 74 dispatches, etc.)
- Honest tone. Not marketing. Not self-deprecating. Just clear.
```

---

## WHAT TO DO AFTER ALL THREE FINISH

1. Review Instance 1's credential audit. If secrets are in git history, decide whether to rotate keys or rewrite history.
2. Review Instance 2's Command Node update. Paste the updated version into a new ChatGPT session and a new Claude web session to verify it provides enough context.
3. Review Instance 3's diary entries. These become the first content on the Replit website.
4. Run the Deep Research prompt (research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md) through Claude Deep Research. This generates the strategy taxonomy for flywheel cycle 1.
5. Set the GitHub repo to public once the credential audit passes.

---

*Generated by JJ, March 7, 2026. The flywheel starts now.*
