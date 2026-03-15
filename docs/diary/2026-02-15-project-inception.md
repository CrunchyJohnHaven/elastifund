# Day 0: February 15, 2026 — The Idea

## What Started This

A question: what happens when you point an AI agent at prediction markets and tell it to maximize returns within safety constraints? Not "AI-assisted trading" where a human decides and the AI recommends. Fully autonomous execution where the agent makes every trade decision and the human only builds infrastructure.

Nobody is doing this in public. Plenty of trading bots exist. None of them are documented openly enough that you can audit the methodology, fork the code, and verify every claim. That gap is the opportunity — not just as a trading system, but as an educational resource.

## What I Did Today

- Registered Polymarket account
- Set up Kalshi account
- Created the GitHub repository (github.com/CrunchyJohnHaven/elastifund)
- Obtained Anthropic API key for Claude
- Started reading academic literature on LLM forecasting

## What I Learned

Prediction markets are significantly less efficient than stock markets. Clinton & Huang (2025) found Polymarket political markets are only ~67% accurate. That means 33% of the time, the crowd is wrong. If an AI can be right more often than the crowd, even slightly, there's money on the table.

But "slightly" is doing a lot of work in that sentence. The academic literature (Schoenegger 2025) shows that most prompt engineering techniques for LLM forecasting actually HURT accuracy. Only one technique reliably helps: base-rate-first prompting, which improves Brier scores by about 0.014. Everything else — chain-of-thought, Bayesian reasoning prompts, elaborate instructions — makes things worse.

This is going to be harder than the "just use GPT" crowd thinks.

## Key Numbers

| Metric | Value |
|--------|-------|
| Capital | $0 |
| Strategies tested | 0 |
| Tests passing | 0 |
| Research dispatches | 1 |

## Tomorrow's Plan

Write the first version of the Claude probability estimation prompt, using base-rate-first structure. Set up the development environment. Start building the scanner that fetches active markets from Polymarket's Gamma API.

---

*Tags: #project-inception #research-cycle*
