# Day 20: March 7, 2026 — Weather Brackets Fail, Latency Geography Wins

## What the Agent Did Today

Two investigations completed. One killed a strategy. The other changed our infrastructure assumptions.

### R10: NOAA Weather Bracket Arb — REJECTED

We tested whether NOAA weather forecasts could beat Kalshi weather bracket markets. The thesis: Kalshi lists weather brackets (e.g., "Will the high temperature in NYC exceed 45°F?") and NWS provides free forecasts. If NWS says 52°F and the market prices the >45°F bracket at only 60%, that's free money.

**The result:** NWS forecast accuracy is 27-35% for exact bracket placement. The forecasts are good at getting the general direction right, but the rounding in NWS data (temperatures reported in whole degrees) creates systematic error at bracket boundaries. When NWS says 45°F, the actual temperature lands within ±3°F, which means you can't confidently say which bracket it'll land in.

**Kill reason:** Model accuracy insufficient. Expected value negative after accounting for bracket boundary uncertainty. Even with GFS + ECMWF + HRRR ensemble (our Edge #1 in the pipeline), the bracket precision problem persists. Weather markets need exact thresholds; weather models provide ranges.

**What we learned:** The issue isn't the data quality — it's the market structure. Binary brackets with exact thresholds are the wrong product for probabilistic weather forecasts. If weather markets asked "Will it rain?" instead of "Will it rain more than 0.10 inches?", the AI would have a clear edge. The bracket precision requirement eliminates it.

### Latency Geography: Dublin Is Already Competitive

We confirmed that Polymarket's CLOB runs in AWS London (eu-west-2), not US infrastructure. Our Dublin VPS (eu-west-1) is 5-10ms away. London colocation would be <1ms. New York is 70-80ms.

**The key finding:** Our latency disadvantage vs London-based bots is 5-10ms. But our current system polls REST APIs every 5 minutes — 300,000ms. The bottleneck is our data ingestion, not our server location. Upgrading to WebSocket feeds (eliminating the 5-minute polling gap) matters 30,000x more than moving to London.

This changes our infrastructure priority: WebSocket upgrade (Dispatch #078) before any geographic optimization.

## Key Numbers

| Metric | Value |
|--------|-------|
| Capital | Internal seed bankroll withheld from public docs |
| Strategies tested to date | 16 (6 deployed, 10 rejected) |
| Strategies in pipeline | 30 |
| Tests passing | 345 |
| Research dispatches | 74 |

## The Flywheel Formalizes

Today we also formalized the research flywheel:
1. RESEARCH — Generate hypotheses via Deep Research prompts
2. IMPLEMENT — Code the top candidates
3. TEST — Run through the pipeline with kill rules
4. RECORD — Document everything
5. PUBLISH — Push to GitHub and website
6. REPEAT — Feed results into next cycle

We wrote the Replit Dashboard v4 spec (769 lines) and the Deep Research Prompt v3 (354 lines). Five parallel dispatches prepared for simultaneous execution across Claude Deep Research, ChatGPT Deep Research, Claude Code, Grok, and Cowork.

The machine is running. The machine publishes. The world learns.

---

*Tags: #strategy-rejected #infrastructure #flywheel-cycle-0*
