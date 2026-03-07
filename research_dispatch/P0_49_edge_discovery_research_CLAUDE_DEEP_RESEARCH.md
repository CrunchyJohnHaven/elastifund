# P0-49: Systematic Edge Discovery — Find Alpha Others Miss
**Tool:** CLAUDE_DEEP_RESEARCH
**Status:** READY
**Priority:** P0 — Our competitive advantage is finding edges nobody else is exploiting
**Expected ARR Impact:** Unknown but potentially massive — one novel edge can transform the system

## Background
Most Polymarket bots use the same playbook: arbitrage, simple LLM prompting, or mechanical strategies. Our advantage is SYSTEM DESIGN INTELLIGENCE — the ability to systematically identify and exploit information asymmetries that other bots aren't looking for.

The research so far identified some edges (NO bias, calibration correction, category routing). But we need to go deeper. What information sources exist that prediction markets don't efficiently price? Where do crowds systematically get it wrong?

## Research Questions

```
I'm building an AI prediction market trading system on Polymarket. I need you to find NOVEL EDGES that most automated traders are NOT exploiting. Go deep.

1. SYSTEMATIC CROWD BIASES IN PREDICTION MARKETS:
   - What specific cognitive biases consistently affect prediction market prices? (beyond favorite-longshot bias, which we already exploit)
   - Anchoring bias: do markets anchor to round numbers (50%, 25%, 75%)?
   - Recency bias: do markets overreact to recent news and then revert?
   - Scope insensitivity: do markets misjudge probabilities of extreme events?
   - Conjunction fallacy: do multi-outcome markets violate probability axioms?
   - What academic papers document exploitable biases in prediction markets?

2. TEMPORAL PATTERNS:
   - Do Polymarket prices show time-of-day patterns? (e.g., more volatile during US trading hours, less efficient overnight)
   - Day-of-week effects? (weekend efficiency drops?)
   - Pre-event patterns: how do prices behave in the final 24/48/72 hours before resolution?
   - Post-news patterns: how quickly does Polymarket incorporate breaking news? Is there a systematic lag?
   - Resolution clustering: do markets near resolution date get more or less efficient?

3. INFORMATION SOURCES THAT MARKETS DON'T PRICE:
   - Government data releases: BLS, BEA, Census, USDA — which government data releases affect prediction markets, and how quickly does the market incorporate them?
   - Regulatory filings: SEC, CFTC, FCC decisions — can upcoming regulatory decisions be predicted from filing patterns?
   - Academic preprints: ArXiv, SSRN — do research papers foreshadow outcomes that prediction markets haven't priced?
   - Expert forecasts: IARPA/ODNI intelligence community forecasts, climate model outputs, disease surveillance (CDC, WHO)
   - Supply chain data: shipping manifests, satellite imagery of factory activity, app download data — for economic prediction markets
   - Congressional floor activity: bill sponsorship counts, committee schedules, amendment patterns — for policy prediction markets

4. STRUCTURAL MARKET MICROSTRUCTURE EDGES:
   - New market premium: when a new market is created, does it start mispriced and converge to efficiency? (trade the convergence)
   - Low-liquidity premium: do thin markets have consistently higher alpha for patient traders?
   - Resolution date proximity: as resolution approaches, do prices become MORE or LESS efficient?
   - Multi-outcome markets: do the individual outcomes sum to >100% or <100%? (overround or underround)
   - Market interconnection: do correlated markets update at different speeds? (e.g., "Will Candidate X win?" vs "Will Party Y win?" — can you front-run one from the other?)

5. NOVEL LLM APPLICATIONS:
   - Can LLMs extract signals from earnings call transcripts, congressional hearings, or press conferences that humans miss?
   - Can LLMs detect subtle language shifts in official communications (Fed minutes, political statements) that predict policy changes?
   - Can LLMs synthesize multiple weak signals (social media + polling + news + expert forecasts) into a stronger combined signal?
   - Has anyone used LLMs to generate counterfactual scenarios that reveal market mispricings?

6. WHAT DO THE BEST FORECASTERS DO?
   - Superforecaster techniques that aren't implemented in any LLM system yet
   - Tetlock's research: what separates the top 2% of forecasters?
   - GJP (Good Judgment Project) published strategies — which are implementable in code?
   - Metaculus top forecasters: what methods do they use?

For each edge you identify, rate it on:
- Novelty (1-5): How likely is it that other bots are already doing this?
- Feasibility (1-5): How hard is it to implement with our tech stack (Python, LLMs, APIs)?
- Magnitude (1-5): How big is the potential alpha?
- Data availability (1-5): Can we actually get the data needed?

I want at minimum 20 specific, actionable edges ranked by these criteria.
```

## Expected Outcome
- Ranked list of 20+ novel edges with feasibility and impact scores
- At least 3-5 implementable within 5 days
- Information source map: what data feeds to integrate first
- Specific cognitive biases to exploit with implementation specs
- Temporal patterns to trade (time-of-day, pre-resolution, etc.)
