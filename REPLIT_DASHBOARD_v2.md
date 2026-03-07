# Replit 2.0 Build Prompt — Predictive Alpha Fund: The Complete Walkthrough

## What This Is

Build a **single-page, scroll-driven educational website** that explains everything Predictive Alpha Fund does — from first principles to implementation details — so that a total layman can read top-to-bottom and understand every strategy, technique, and system we've built. This is a learning resource, a methodology showcase, and an investor walkthrough all in one.

**The thesis on every page:** We build bots that do whatever non-harmful activity produces the best returns. The bots drive strategy execution. We humans generate ideas, add value, and apply compute and resources. This is a human + AI partnership.

**Critical constraint:** Single page. No multi-page routing. One continuous scroll, section-by-section, so it can be exported/printed as a single PDF in one shot. Use a sticky sidebar table of contents for navigation.

**Stack:** Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts for charts, Framer Motion for scroll-triggered animations. Dark mode only (cleaner for PDF export).

**Deployment:** Replit with custom domain. Fast, responsive, mobile-friendly.

---

## Design Philosophy

- **Dark mode only.** Deep blacks (#0a0a0a), charcoal grays (#111, #1a1a1a), electric accents: green (#22c55e) for profit, red (#ef4444) for loss, cyan (#06b6d4) for data, amber (#f59e0b) for warnings, violet (#8b5cf6) for research.
- **Visual-first.** Every concept gets a diagram, chart, or visual explanation BEFORE any dense text. If a layman's eyes glaze over, we've failed.
- **Progressive disclosure.** Start simple, go deep. Each section opens with a "plain English" summary card, then reveals the technical details.
- **Monospace** for numbers (JetBrains Mono). Clean sans-serif (Inter) for prose.
- **Glassmorphism cards** with subtle borders (`border border-white/10 bg-white/5 backdrop-blur`).
- **Scroll-triggered animations** — elements fade/slide in as you scroll to them.
- **Sticky sidebar TOC** on the left (desktop) with scroll-spy highlighting. Collapses to a floating hamburger on mobile.
- **"Fellow enthusiasts" energy** — technical, transparent, curious. We're sharing what we've built and inviting people to learn.

---

## Page Structure (Single Continuous Scroll)

The page is divided into **18 sections**, each with a section divider featuring a large section number and title. Think of it like chapters in a book, but all on one page.

**CRITICAL DESIGN PRINCIPLE:** Every single section ties back to THE NUMBER (+403% simulated ARR). Each section header should include a small tag indicating its relationship to the number:

- Sections that explain HOW we get the number → tag: `📐 How we get to +6,007%`
- Sections that increase CONFIDENCE in the number → tag: `✅ Why you should believe it`
- Sections that decrease confidence (risks) → tag: `⚠️ Why you should be skeptical`
- Sections about making the number BIGGER → tag: `📈 How we improve it`
- Sections about the mission → tag: `💜 Where it goes`

This tagging system keeps the reader oriented. They always know why they're reading a given section.

---

### Section 0: Hero

Full-viewport hero section. Subtle animated grid background (like graph paper, very faint). This is the most important section of the entire page. It needs to grab someone in 5 seconds and make them want to scroll.

**The hero has THREE beats that unfold in sequence. The page loads, and the user experiences them one after another.**

---

**BEAT 1: THE NUMBER**

Before anything else — before the title, before any words — THE NUMBER appears. Massive. Center screen. Animated count-up from 0%. This is the first thing anyone sees.

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│                                                                  │
│                        +6,007%                                   │
│                                                                  │
│                   Simulated Annual Return                        │
│                                                                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Builder specs for THE NUMBER:**
- Font size: absolutely massive. 120px+ on desktop, 72px+ on mobile. This number should dominate the viewport.
- Color: bright green (#22c55e) with a subtle glow/bloom effect behind it
- Animation: counts up from 0% to +6,007% over ~2.5 seconds on page load, with easing (fast start, slow finish). The comma should appear naturally as the count passes 1,000.
- The "%" should be slightly smaller than the digits
- Below it, in muted gray text (20px): "Simulated Annual Return"
- Below THAT, even smaller, muted: "Velocity-optimized · Backtested on 532 markets · Not live trading" [FIXED]

**Why +6,007%?** This is the velocity-optimized ARR — the number we're actually targeting. Velocity-sorted top-5 trades per cycle, 71.7% win rate, fast-resolving markets only, capital recycled aggressively. We optimize for SPEED of capital turnover, not conservative position sizing. Starting with $2K and adding $1K/week of disposable income. This is the number we're chasing. Below it we show the range from conservative to aggressive so people can calibrate.

**NOTE TO BUILDER:** THE NUMBER should be dynamically configurable. As we improve the system, we update one constant and the entire page updates. Start with +6,007% (velocity-max). The data constant is `THE_NUMBER.arr_velocity_max`.

**The entire rest of the page exists to answer two questions about this number:**
1. **How confident should you be in it?** (every strategy detail, backtest, risk section adds or subtracts confidence)
2. **How do we make it bigger?** (every roadmap item, research finding, and planned improvement)

**This framing should be stated explicitly on the page. Below the number, add two small link-style lines:**

```
                        +6,007%
                   Simulated Annual Return

          ↓ How confident should you be in this number?
          ↓ How are we trying to make it bigger?
```

These two lines are anchor links — clicking the first scrolls to the methodology/backtest sections, clicking the second scrolls to the roadmap.

---

**BEAT 2: THE PROBLEM (appears after a 1-second delay, below the number)**

The personal story. Display as large, clean text. Each line fades in one at a time (0.5s stagger). Warm white/cream color against the dark background. No boxes, no cards — just the words breathing on the page.

```
The problem I set out to solve:

  1. I wanted to use AI to build AI.

  2. I wanted what I build to actually be useful.

  3. I wanted what I build to actually make the world better.

  4. I wanted to do it with my friends.
```

**Pause. Then the answer fades in below (slightly brighter, subtle gradient glow):**

```
This project is my answer to all four.
```

---

**BEAT 3: THE FORMULA (appears below, flowing naturally from Beat 2)**

Each term on its own line, animating in with a slight bounce. Each line gets a subtle colored accent. The thesis restated in universal terms:

```
People Want =

  Fun Stuff                           ← (amber accent)
+ Stuff That Makes Money              ← (green accent)
+ Stuff That Makes the World Better   ← (violet accent)
+ With Friends                        ← (cyan accent)

This project is all four.
```

**Builder note:** Beats 2 and 3 should feel like ONE continuous moment — personal story flowing into universal insight. No hard visual break between them.

---

**SUPPORTING METRICS** — Below the three beats, a row of smaller counter cards that add credibility to THE NUMBER:

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│    71.2%          │  │    532            │  │    0.0%           │  │    16.43          │
│    Win Rate       │  │    Markets        │  │    Ruin Prob      │  │    Sharpe Ratio   │
│    (best variant) │  │    Backtested     │  │    (Monte Carlo)  │  │    (annualized)   │
└──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘
```

**THE ARR CONFIDENCE METER** — A novel visual element. Below the counter cards, show a horizontal gauge/meter:

```
┌──────────────────────────────────────────────────────────────────┐
│  CONFIDENCE IN THIS NUMBER                                       │
│                                                                  │
│  ░░░░░░████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  0%                    32%                                  100% │
│                                                                  │
│  What increases confidence:          What decreases confidence:  │
│  ✅ 532-market backtest              ❌ Zero live trades          │
│  ✅ Out-of-sample validation         ❌ Brier barely beats random│
│  ✅ Fee-adjusted numbers             ❌ Competitive pressure     │
│  ✅ Monte Carlo 0% ruin              ❌ Edge may erode           │
│  ✅ Conservative Kelly sizing        ❌ Platform risk            │
│                                                                  │
│  Every section below either adds ✅ or acknowledges ❌            │
│  to this confidence score.                                       │
└──────────────────────────────────────────────────────────────────┘
```

**Builder note on the confidence meter:**
- The 38% is an editorial estimate — honest about where we are (strong backtest, zero live data)
- The meter should be interactive: as you scroll through sections, the meter updates in the sticky nav to show which confidence factors you've read about
- This is OPTIONAL to implement interactively — a static version is fine for v1

**Disclaimer banner** (always visible, amber border):
> "⚠️ All performance data is from backtesting against historical data. Zero live trades have resolved. Past performance does not guarantee future results."

**Scroll indicator:** Animated down-arrow with text "Scroll to learn everything ↓"

---

**ARR SCENARIO STRIP** — A thin horizontal strip below the disclaimer showing the range:

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  Conservative      Moderate          Aggressive    ★ VELOCITY ★ │
│   +124%            +403%             +872%        ★ +6,007% ★   │
│                                                                  │
│  64.9% WR          71.2% WR         76.2% WR      71.7% WR     │
│  3 trades/day      5 trades/day     8 trades/day   5/day fast   │
│  Baseline          Cal+Filter+Asym  NO-only        Top-5 veloc  │
│  Quarter-Kelly     Quarter-Kelly    Quarter-Kelly  Full velocity │
│                                                                  │
│  ★ = Our target strategy (shown above)                          │
│  We optimize for SPEED of capital turnover, not safety.         │
│  This is disposable income deployed for maximum expected return. │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

This strip gives context: +6,007% is the aggressive, velocity-optimized target. The conservative floor is still +124%. We deliberately choose to maximize expected value over minimizing risk — this is disposable capital.

**CAPITAL DEPLOYMENT SCHEDULE** — Show below the scenario strip:

```
┌──────────────────────────────────────────────────────────────────┐
│  CAPITAL DEPLOYMENT                                              │
│                                                                  │
│  Week 0:   $2,000 seed capital                                  │
│  Week 1:  +$1,000 ($3,000 total)                               │
│  Week 2:  +$1,000 ($4,000 total)                               │
│  Week 3:  +$1,000 ($5,000 total)                               │
│  Week 4:  +$1,000 ($6,000 total)                               │
│  ...continuing $1K/week from disposable income                  │
│                                                                  │
│  At velocity-optimized returns, each dollar added                │
│  starts compounding immediately into fast-resolving markets.     │
│                                                                  │
│  This is not money we can't afford to lose.                     │
│  This IS money we're deploying for maximum expected return.      │
└──────────────────────────────────────────────────────────────────┘
```

---

### Section 1: The Mission — Why We Do This

**Plain English summary card (highlighted, full-width, violet accent):**
> "This isn't just a trading project. Every dollar of net profit goes toward veteran suicide prevention and mental health support. We build AI that makes money so we can fund the people and organizations saving lives."

#### Visual 1.0: THE VISION — Vibe Code Agents That Do Everything

**THIS IS THE CENTERPIECE VISUAL OF THE ENTIRE PAGE.** Build it as a full-width, visually stunning, animated section. Think of it like a manifesto page — dark background, glowing elements, kinetic typography.

**Build as an animated three-column layout with a central hub:**

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│                        THE VISION                                        │
│                                                                          │
│          Anyone can vibe code an agent.                                  │
│          Agents can do anything non-harmful.                            │
│          Some make money. Some volunteer. Some build.                   │
│          All of it adds up.                                             │
│                                                                          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐       │
│  │                  │  │                  │  │                  │       │
│  │  🤖 MONEY BOTS   │  │  🤝 VOLUNTEER    │  │  🔨 BUILDER      │       │
│  │                  │  │     AGENTS       │  │     AGENTS       │       │
│  │  Trading bots    │  │                  │  │                  │       │
│  │  that find edge  │  │  Agents that go  │  │  Agents that     │       │
│  │  in prediction   │  │  out and donate  │  │  create tools,   │       │
│  │  markets, arb    │  │  their time.     │  │  websites, apps  │       │
│  │  opportunities,  │  │  Research for    │  │  for nonprofits  │       │
│  │  and any legal   │  │  nonprofits.     │  │  and communities │       │
│  │  profit source.  │  │  Write grants.   │  │  that need them. │       │
│  │                  │  │  Analyze data.   │  │                  │       │
│  │  Profits fund    │  │  Build reports.  │  │  Open-source     │       │
│  │  the mission.    │  │  Find resources. │  │  everything.     │       │
│  │                  │  │                  │  │                  │       │
│  │  "Vibe code a    │  │  "Vibe code an   │  │  "Vibe code an   │       │
│  │   trading bot"   │  │   agent that     │  │   agent that     │       │
│  │                  │  │   volunteers"    │  │   builds things" │       │
│  │                  │  │                  │  │                  │       │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘       │
│           │                     │                      │                │
│           └─────────────────────┼──────────────────────┘                │
│                                 │                                       │
│                                 ▼                                       │
│                    ┌──────────────────────┐                             │
│                    │                      │                             │
│                    │    VETERAN MENTAL    │                             │
│                    │    HEALTH & SUICIDE  │                             │
│                    │    PREVENTION        │                             │
│                    │                      │                             │
│                    │    Every dollar,     │                             │
│                    │    every hour,       │                             │
│                    │    every agent       │                             │
│                    │    → saving lives    │                             │
│                    │                      │                             │
│                    └──────────────────────┘                             │
│                                                                          │
│  ─────────────────────────────────────────────────────────────────       │
│                                                                          │
│  THE GAME:                                                              │
│                                                                          │
│  1. You have ideas → Tell an AI → It builds an agent                   │
│  2. The agent runs autonomously → Makes money or does good             │
│  3. Profits go to veterans → Impact compounds                          │
│  4. Everything is open-source → Anyone can fork, improve, remix        │
│  5. The community grows → More agents → More impact                    │
│                                                                          │
│  You don't need to be a programmer.                                    │
│  You don't need to be a trader.                                        │
│  You just need curiosity and an AI subscription.                       │
│                                                                          │
│  "Vibe coding" = describing what you want in plain English             │
│  and letting AI build it. That's all it takes.                         │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Animation notes for the builder:**
- The three columns should fade in one at a time (left → center → right) with a 0.5s delay
- The arrows should animate downward to the "Veteran Mental Health" hub
- The hub should pulse with a subtle glow
- "THE GAME" steps should appear one at a time on scroll, like a typewriter effect
- Use a gradient background for this section (subtle deep purple → dark blue → black)
- Consider adding floating particle effects (very subtle, like stars) behind the three columns

**Below the vision block, add a CTA card:**

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   🚀 WANT TO BUILD AN AGENT?                                    │
│                                                                  │
│   Start here:                                                   │
│                                                                  │
│   1. Pick a problem (trading edge, volunteer task, or build)    │
│   2. Describe it to an AI in plain English                      │
│   3. Iterate until it works                                     │
│   4. Deploy it (we'll help)                                     │
│   5. Watch it run and improve it over time                      │
│                                                                  │
│   [Browse the Prompt Queue →]  [See Current Agents →]           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

#### Visual 1.0b: The Mission Statement

**Large, centered block with a subtle background image (American flag or abstract gradient):**

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   Every day, approximately 17 veterans die by suicide            │
│   in the United States.                                          │
│                                                                  │
│   We're building AI that generates returns —                     │
│   and directing those returns to organizations                   │
│   that address veteran mental health, physical health,           │
│   and suicide prevention.                                        │
│                                                                  │
│   This is a project where making money IS doing good.            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

#### Visual 1.1: How the Money Flows

**Build as an animated Sankey/flow diagram:**

```
┌──────────────┐
│  AI TRADING  │
│  BOT PROFITS │
│              │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│                 NET RETURNS                        │
│                                                   │
│  ┌───────────────────┐   ┌─────────────────────┐ │
│  │                   │   │                     │ │
│  │  YOUR PRINCIPAL   │   │  PROFITS            │ │
│  │  Returned to you  │   │                     │ │
│  │  in full          │   │  ┌───────────────┐  │ │
│  │                   │   │  │ 80% → Veteran │  │ │
│  │                   │   │  │ nonprofits    │  │ │
│  │                   │   │  ├───────────────┤  │ │
│  │                   │   │  │ 20% → You     │  │ │
│  │                   │   │  │ (your return) │  │ │
│  │                   │   │  ├───────────────┤  │ │
│  │                   │   │  │ Management fee│  │ │
│  │                   │   │  │ (operations)  │  │ │
│  └───────────────────┘   │  └───────────────┘  │ │
│                          └─────────────────────┘ │
└──────────────────────────────────────────────────┘

You donate money or time.
Your principal comes back.
You keep 20% of profits.
80% of profits go to saving veteran lives.
A reasonable management fee covers operations.
```

#### Visual 1.2: How Anyone Can Contribute

**This is a key differentiator. Build as a two-path visual:**

```
┌──────────────────────────────────────────────────────────────────┐
│  TWO WAYS TO CONTRIBUTE                                          │
│                                                                  │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐   │
│  │  💰 DONATE MONEY        │  │  🧠 DONATE TIME (LLM TOKENS)│   │
│  │                         │  │                             │   │
│  │  Invest capital into    │  │  Got unused ChatGPT Plus,   │   │
│  │  the trading fund.      │  │  Claude Pro, or Grok        │   │
│  │                         │  │  tokens sitting around?     │   │
│  │  Your principal is      │  │                             │   │
│  │  returned. You keep     │  │  We break down everything   │   │
│  │  20% of profits.        │  │  the project needs into a   │   │
│  │  80% goes to veterans.  │  │  QUEUE OF PROMPTS anyone    │   │
│  │                         │  │  can run.                   │   │
│  │  Management fee covers  │  │                             │   │
│  │  infrastructure only.   │  │  Pick a prompt. Paste it.   │   │
│  │                         │  │  Run it. Submit the output. │   │
│  │                         │  │  You just contributed to a  │   │
│  │                         │  │  project that makes money   │   │
│  │                         │  │  AND saves lives.           │   │
│  └─────────────────────────┘  └─────────────────────────────┘   │
│                                                                  │
│  Whether you have $100 or 100 unused ChatGPT messages,          │
│  you can add value to this project.                             │
└──────────────────────────────────────────────────────────────────┘
```

**Below this, show the prompt queue concept:**

```
┌──────────────────────────────────────────────────────────────────┐
│  THE PROMPT QUEUE — How "donating time" works                    │
│                                                                  │
│  We maintain a library of 60+ research prompts, each designed   │
│  to run in a specific AI tool. You don't need to be a quant    │
│  or a programmer. You just need an AI subscription.             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ EXAMPLE PROMPT (for ChatGPT Deep Research):              │    │
│  │                                                          │    │
│  │ "Research the top 10 veteran mental health nonprofits    │    │
│  │  in the US by: outcomes data, dollars per veteran        │    │
│  │  served, suicide prevention programs, and transparency   │    │
│  │  ratings. Rank them by cost-effectiveness."              │    │
│  │                                                          │    │
│  │  Tool: ChatGPT Deep Research                             │    │
│  │  Priority: P1                                            │    │
│  │  Est. time: 5 minutes                                    │    │
│  │  Status: 🟡 Available                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  We have prompts for:                                           │
│  • ChatGPT (Deep Research mode) — market research, nonprofits  │
│  • Claude (Claude Code / Cowork) — code, analysis, documents   │
│  • Grok — real-time news analysis, social sentiment            │
│  • Any LLM — general research, writing, data analysis          │
│                                                                  │
│  Each prompt is self-contained. Copy, paste, run, submit.       │
│  No coding required. No finance knowledge required.             │
│  Your unused AI tokens → research that improves the system      │
│  → better returns → more money for veterans.                    │
└──────────────────────────────────────────────────────────────────┘
```

---

### Section 2: The Big Picture — What Are We Doing?

**Plain English summary card (highlighted, full-width):**
> "We built an AI that reads prediction market questions — things like 'Will it snow in NYC this week?' or 'Will the Fed cut rates?' — estimates the true probability of each event, compares its estimate to what the market thinks, and bets when it spots a meaningful disagreement. That's it. Find mispricings, bet on them, make money when reality proves us right."

#### Visual 1.1: The Core Loop Diagram

**BUILD THIS AS AN ANIMATED FLOW DIAGRAM** (SVG or canvas, with arrows that pulse/animate on scroll):

```
┌─────────────────────────────────────────────────────────────────────┐
│                        THE PREDICTION LOOP                          │
│                                                                     │
│   ┌──────────┐     ┌──────────────┐     ┌──────────────────┐       │
│   │ SCAN     │────▶│ ESTIMATE     │────▶│ COMPARE          │       │
│   │          │     │              │     │                  │       │
│   │ Find 100 │     │ AI estimates │     │ AI says 75%      │       │
│   │ markets  │     │ true prob    │     │ Market says 50%  │       │
│   │ every    │     │ from first   │     │ Gap = 25%        │       │
│   │ 5 min    │     │ principles   │     │ = "EDGE"         │       │
│   └──────────┘     └──────────────┘     └────────┬─────────┘       │
│                                                   │                 │
│                                                   ▼                 │
│   ┌──────────┐     ┌──────────────┐     ┌──────────────────┐       │
│   │ LEARN    │◀────│ RESOLVE      │◀────│ BET              │       │
│   │          │     │              │     │                  │       │
│   │ Update   │     │ Event        │     │ Bet size based   │       │
│   │ calibra- │     │ happens      │     │ on confidence    │       │
│   │ tion     │     │ (or not)     │     │ (Kelly criterion)│       │
│   │ model    │     │ Win or lose  │     │ Risk-managed     │       │
│   └──────────┘     └──────────────┘     └──────────────────┘       │
│                                                                     │
│   This loop runs automatically, 24/7, on a cloud server.           │
└─────────────────────────────────────────────────────────────────────┘
```

**Animate each box highlighting in sequence** with a 1-second delay between steps, looping continuously.

#### Visual 1.2: What Is a Prediction Market?

**Interactive explainer card** showing a real example:

```
┌───────────────────────────────────────────────────────────────────┐
│  EXAMPLE: "Will it snow more than 3 inches in NYC this week?"     │
│                                                                   │
│  Market Price: $0.40  ← This means the crowd thinks 40% chance   │
│  Our AI says:  $0.65  ← We think it's actually 65% chance        │
│                                                                   │
│  ┌─────────────────────────────────────────────────┐              │
│  │  0%    20%    40%    60%    80%    100%          │              │
│  │  ├──────┼──────┼──────┼──────┼──────┤           │              │
│  │               ▲             ▲                    │              │
│  │            Market        Our AI                  │              │
│  │            (40¢)         (65%)                   │              │
│  │                                                  │              │
│  │         ◀── 25% EDGE ──▶                        │              │
│  └─────────────────────────────────────────────────┘              │
│                                                                   │
│  ACTION: Buy YES shares at 40¢ each.                             │
│  If it snows 3+ inches: each share pays $1.00 → profit $0.60    │
│  If it doesn't:          each share pays $0.00 → lose $0.40     │
│                                                                   │
│  With a 65% true probability, expected value = +$0.25/share      │
└───────────────────────────────────────────────────────────────────┘
```

#### Visual 1.3: The Human + Bot Partnership

**Two-column layout showing the division of labor:**

```
┌─────────────────────────────┐  ┌─────────────────────────────┐
│  🧠 HUMANS DO               │  │  🤖 BOTS DO                 │
│                             │  │                             │
│  • Generate strategy ideas  │  │  • Scan 100 markets / 5min  │
│  • Design the AI prompts    │  │  • Estimate probabilities   │
│  • Analyze research papers  │  │  • Size every bet optimally │
│  • Set risk parameters      │  │  • Execute trades 24/7      │
│  • Interpret backtest data  │  │  • Track risk in real-time  │
│  • Allocate capital         │  │  • Send alerts via Telegram │
│  • Make strategic pivots    │  │  • Log every decision       │
│  • Build the next version   │  │  • Never sleep, never panic │
└─────────────────────────────┘  └─────────────────────────────┘
```

---

### Section 2: The AI Brain — How We Estimate Probabilities

**Plain English summary:**
> "The most important thing our system does is estimate how likely something is to happen. We use Claude (an AI model by Anthropic) to read a market question, think through it step by step, and output a probability. But there's a critical trick: we NEVER show the AI what the market thinks. If we did, it would just copy the market price — and that's useless."

#### Visual 2.1: The Anchoring Problem

**Before/After comparison — TWO side-by-side charts:**

```
BEFORE: Claude sees market price             AFTER: Claude doesn't see market price

AI Estimate vs Market Price                  AI Estimate vs Market Price
100% │          ·  ·                         100% │     ·   ·
     │        · ·                                 │  ·    ·    ·
 80% │      · ·                               80% │·  ·      ·
     │    ··                                      │    ·  ·      ·
 60% │  ··                                    60% │ ·    ·   ·
     │ ·                                          │·   ·   ·    ·
 40% │·                                       40% │  ·  ·     ·
     │                                            │ ·  ·   ·
 20% │                                        20% │·    ·
     │                                            │
  0% └────────────────                         0% └────────────────
     0%  20%  40%  60%  80% 100%                  0%  20%  40%  60%  80% 100%
              Market Price                                 Market Price

     Correlation: 0.994                            Avg Divergence: 25.7%
     "Just copying the market"                     "Independent thinking"
     = USELESS                                     = EDGE
```

**Build these as actual Recharts scatter plots** with the data points and trend lines. The "before" chart should have a tight diagonal line. The "after" chart should have scattered points showing genuine disagreement.

#### Visual 2.2: The 6-Step Reasoning Process

**Build as a vertical stepper/timeline component** where each step expands on click:

```
Step 1: OUTSIDE VIEW (Base Rate)
   │  "Before looking at this specific question, what's the
   │   historical frequency of similar events?"
   │  Example: "How often does it snow 3+ inches in NYC in March?
   │   Historical base rate: ~25% of March weeks"
   │
Step 2: ARGUMENTS FOR (YES)
   │  List 3-5 reasons this could happen
   │  Each rated: weak / moderate / strong
   │  "Current cold front, La Niña pattern, NWS advisory issued"
   │
Step 3: ARGUMENTS AGAINST (NO)
   │  List 3-5 reasons this might NOT happen
   │  Each rated: weak / moderate / strong
   │  "Temperature forecast is borderline, storm track uncertain"
   │
Step 4: INITIAL ESTIMATE
   │  "Based on the above: ~60%"
   │
Step 5: CALIBRATION CHECK
   │  "Am I being overconfident? Studies show I tend to
   │   overestimate YES outcomes by 20-30%. Let me adjust."
   │
Step 6: FINAL PROBABILITY
   ▼  "65.0%"
```

**Below the stepper, show a callout box:**
> "Why this specific structure? We tested dozens of prompt designs. Academic research (Schoenegger 2025) tested 38 different prompting strategies. Only ONE actually improved predictions: starting with the base rate. Everything else — Bayesian reasoning, chain-of-thought, 'think like a superforecaster' — either didn't help or actively HURT accuracy."

#### Visual 2.3: Category Routing — Where AI Has Edge

**Build as a horizontal bar chart or tier list visual:**

```
CATEGORY EDGE RANKING (where should the bot focus?)

TIER S — STRONG EDGE                           Trade aggressively
├── 🌦️ Weather    │████████████████████│  Best category. Retail traders
│                 │                    │  use gut feel. We use NWS data.
├── 🏛️ Politics   │██████████████████  │  Structural partisan bias.
│                 │                    │  Polls beat sentiment.

TIER A — MODERATE EDGE                         Trade normally
├── 📊 Economics  │████████████████    │  Macro data + LLM reasoning.
├── ❓ Unknown    │██████████████      │  Misc markets. Case-by-case.

TIER B — WEAK EDGE                             Trade with caution
├── 🌍 Geopolitics│████████            │  Ambiguous resolution.
│                 │                    │  Long capital lock-up.

TIER F — NO EDGE                               DO NOT TRADE
├── 💰 Crypto     │██                  │  Speed-dependent. Arb bots win.
├── ⚽ Sports     │█                   │  Sharps + data providers dominate.
├── 🏦 Fed Rates  │█                   │  Directly arb'd against CME futures.
└─────────────────┘
```

Use colored bars: green for S-tier, blue for A, yellow for B, red for F.

---

### Section 3: Calibration — Fixing the AI's Overconfidence

**Plain English summary:**
> "Raw AI predictions are overconfident. When Claude says '90% likely,' the real probability is closer to 71%. We fix this with a statistical technique called Platt scaling — basically, we ran Claude on 532 past markets, measured how wrong it was, and built a correction formula. Now when Claude says 90%, we automatically adjust it down to 71%."

#### Visual 3.1: The Overconfidence Problem — Reliability Diagram

**Build as a Recharts line chart with two lines:**

```
RELIABILITY DIAGRAM: Predicted vs Actual Probability

100% │                                          ╱ Perfect
     │                                        ╱   calibration
 80% │                              ·───·   ╱     (diagonal)
     │                        ·───·       ╱
 60% │                  ·───·           ╱
     │            ·───·              ╱        ── After Platt
 40% │      ·───·                 ╱              Scaling
     │·───·                    ╱
 20% │                      ╱                 ── Before (raw)
     │  ·───·            ╱                       Claude is HERE
 10% │·                ╱                         (below the line =
  0% └──────────────────────────────              overconfident)
     0%   20%   40%   60%   80%   100%
              Claude's Prediction
```

The key visual: the "Before" line should clearly bow below the diagonal (overconfident), and the "After" line should hug the diagonal much more closely.

#### Visual 3.2: The Correction Map

**Build as an animated transformation visual** — a number goes in on the left, gets corrected, comes out on the right:

```
┌──────────────────────────────────────────────────────────┐
│  CALIBRATION CORRECTION MAP                              │
│                                                          │
│  Claude says  ──▶  Platt scaling  ──▶  We actually use   │
│                                                          │
│     95%       ──▶   ████████████  ──▶    79.3%          │
│     90%       ──▶   ██████████    ──▶    71.1%          │
│     80%       ──▶   ████████      ──▶    60.0%          │
│     70%       ──▶   ██████        ──▶    52.6%          │
│     50%       ──▶   █████         ──▶    40.2%          │
│     20%       ──▶   ███           ──▶    22.8%          │
│      5%       ──▶   ██            ──▶    10.5%          │
│                                                          │
│  Formula: calibrated = 1/(1 + e^(-(A×logit + B)))       │
│  Where A = 0.5914, B = -0.3977                          │
│  Fitted on 372 markets, validated on 160 held-out       │
└──────────────────────────────────────────────────────────┘
```

#### Visual 3.3: Validation — Did It Actually Work?

**Side-by-side metric cards:**

```
┌──────────────────────────┐    ┌──────────────────────────┐
│  TRAINING SET (372)      │    │  TEST SET (160)          │
│                          │    │  (never seen before)     │
│  Raw Brier:    0.2188    │    │  Raw Brier:    0.2862    │
│  Platt Brier:  0.2050    │    │  Platt Brier:  0.2451    │
│  Improvement: +0.0138    │    │  Improvement: +0.0411    │
│                          │    │                          │
│  ✅ Better               │    │  ✅ MUCH better          │
└──────────────────────────┘    └──────────────────────────┘

Note: Lower Brier = better. Random chance = 0.25.
Our calibrated system beats random on held-out data.
```

**Callout box:**
> "What's a Brier Score? It's the standard accuracy metric for probability predictions. It measures the average squared error between your predicted probability and what actually happened (0 or 1). A score of 0 is perfect, 0.25 is random coin-flipping, and higher is worse than random. Our calibrated score of 0.245 on unseen data means we're genuinely, if modestly, better than chance."

---

### Section 4: Position Sizing — How Much to Bet (Kelly Criterion)

**Plain English summary:**
> "Knowing WHAT to bet on is only half the game. Knowing HOW MUCH to bet is equally important. Bet too much and one bad streak wipes you out. Bet too little and your edge barely compounds. We use a 200-year-old formula called the Kelly Criterion that tells you the mathematically optimal bet size based on your edge and the odds."

#### Visual 4.1: The Kelly Criterion Explained

**Build as a visual equation with annotations:**

```
┌──────────────────────────────────────────────────────────────────┐
│  THE KELLY FORMULA FOR PREDICTION MARKETS                        │
│                                                                  │
│  For a BUY YES trade:                                            │
│                                                                  │
│         edge                   (what you know − what market knows)│
│  f* = ─────────── =  ───────────────────────────────────────────│
│        1 − price              (maximum you can profit per $1)    │
│                                                                  │
│  EXAMPLE:                                                        │
│  Our AI says 65% true probability                                │
│  Market price is 40¢                                             │
│  Edge = 65% − 40% = 25%                                         │
│  f* = 0.25 / (1 − 0.40) = 0.417 = 41.7% of bankroll           │
│                                                                  │
│  That means: if you have $1,000, Kelly says bet $417.            │
│  That's AGGRESSIVE. That's why we use a fraction of Kelly.       │
└──────────────────────────────────────────────────────────────────┘
```

#### Visual 4.2: Why We Use Quarter-Kelly (The Risk/Reward Tradeoff)

**Build as a Recharts line chart** with growth rate on Y-axis and Kelly fraction on X-axis, plus a data table below:

```
GROWTH RATE vs KELLY FRACTION

Growth │
Rate   │                    * Full Kelly
       │                  *   (max growth,
       │                *      max pain)
       │              *
       │            *
       │          *  ← Half Kelly (sweet spot for aggressive)
       │        *
       │      * ← Quarter Kelly ★ WE ARE HERE
       │    *     (75% of max growth, tiny ruin risk)
       │  *
       │*  ← Tenth Kelly (very safe, slow growth)
       │
       └──────────────────────────────────────────
       0    0.1   0.25  0.5    0.75    1.0
                    Kelly Fraction

┌────────────┬───────────────┬──────────────┬───────────┬────────┐
│ Fraction   │ Median Growth │ P(50% DD)    │ Ruin Risk │ Sharpe │
├────────────┼───────────────┼──────────────┼───────────┼────────┤
│ Full (1×)  │ ~10¹⁶×        │ 100%         │ 36.9%     │ 0.37   │
│ Half (0.5×)│ ~10¹¹×        │ 94.7%        │ ~0%       │ 0.57   │
│ ★ Qtr(0.25)│ ~10⁶×         │ 8.0%         │ 0%        │ 0.64   │
│ Tenth(0.1×)│ ~10²×         │ 0%           │ 0%        │ 0.68   │
└────────────┴───────────────┴──────────────┴───────────┴────────┘

The takeaway: Quarter-Kelly gives us 0% ruin risk, a 0.64 Sharpe,
and still compounds at ~10⁶× over the full simulation. That's the
sweet spot between "grow fast" and "don't blow up."
```

#### Visual 4.3: Asymmetric Sizing — Leaning Into Our Strongest Edge

**Build as a two-panel visual:**

```
┌──────────────────────────────┐  ┌──────────────────────────────┐
│  BUY YES TRADES              │  │  BUY NO TRADES               │
│                              │  │                              │
│  Win rate: 55.8%             │  │  Win rate: 76.2%             │
│  Kelly mult: 0.25×           │  │  Kelly mult: 0.35×           │
│  Sizing: Conservative        │  │  Sizing: Aggressive          │
│                              │  │                              │
│  ████████░░░░░░░░░░░░        │  │  ████████████████░░░░        │
│  "Decent edge, bet less"     │  │  "Strong edge, bet more"     │
└──────────────────────────────┘  └──────────────────────────────┘

WHY THE DIFFERENCE?

Buy NO exploits the "favorite-longshot bias" — prediction market
traders systematically overprice exciting YES outcomes. People WANT
to bet that things will happen. We profit by betting they won't.

This is a well-documented market inefficiency (Whelan 2025, Becker 2025).
Contracts priced at 5¢ actually win only 2-4% of the time, not 5%.
```

#### Visual 4.4: Backtest — Kelly vs Flat Betting

**Build as a Recharts area chart showing two wealth paths:**

```
PORTFOLIO GROWTH: FLAT $2 BETS vs QUARTER-KELLY

$1,400 │                                          ╱ Quarter-Kelly
       │                                        ╱   $1,353 (+1,704%)
$1,200 │                                      ╱
       │                                    ╱
$1,000 │                                  ╱
       │                                ╱
  $800 │                              ╱
       │                            ╱
  $600 │                          ╱
       │                   ·····╱····· Flat $2
  $400 │             ·····╱····        $330 (+341%)
       │       ·····╱····
  $200 │ ·····╱····
       │╱····
   $75 └──────────────────────────────────────────
       0     100    200    300    400    500   532
                        Markets Resolved

       Kelly outperformance: +309%
       Same trades, same outcomes — only the sizing changed.
```

---

### Section 5: Capital Velocity — Speed Is a Multiplier

**Plain English summary:**
> "A bet that resolves in 2 days and earns 30% return generates 15× more annualized return than the same bet resolving in 30 days. We prioritize fast-resolving markets because your money is freed up to bet again sooner. This single optimization improved our annualized returns by +432%."

#### Visual 5.1: The Velocity Concept

**Build as an animated comparison:**

```
THE SAME $100 BET, TWO DIFFERENT SPEEDS:

SLOW (30-day resolution):
  $100 ──────────────────────────────▶ $130  (30% return)
  Day 1                               Day 30
  Annualized: 30% × (365/30) = 365%

FAST (2-day resolution):
  $100 ──▶ $130 ──▶ $169 ──▶ $220 ──▶ $286 ──▶ ... (reinvest each win)
  Day 1   Day 3   Day 5   Day 7   Day 9    ...
  Annualized: 30% × (365/2) = 5,475%

  SAME EDGE. 15× MORE RETURN. Speed is the multiplier.
```

#### Visual 5.2: Velocity Score Formula

```
┌────────────────────────────────────────────────────┐
│  VELOCITY SCORE = (edge / days_to_resolve) × 365   │
│                                                    │
│  Example A: 25% edge, resolves in 2 days           │
│  Score = (0.25 / 2) × 365 = 45.6                  │
│                                                    │
│  Example B: 25% edge, resolves in 30 days          │
│  Score = (0.25 / 30) × 365 = 3.0                  │
│                                                    │
│  The bot ranks ALL signals by velocity score       │
│  and takes the top 5 each cycle.                   │
└────────────────────────────────────────────────────┘
```

#### Visual 5.3: Velocity Backtest Results

**Build as a bar chart + comparison table:**

```
WIN RATE BY RESOLUTION SPEED:

< 24 hours  │████████████████████████████████████│ 72.1%  $0.88/trade
1-3 days    │█████████████████████████████████████████│ 81.8%  $1.27/trade
1-4 weeks   │██████████████████████████████│ 59.9%  $0.39/trade
> 1 month   │██████████████████████████████████│ 69.0%  $0.76/trade

KEY INSIGHT: Fast markets win MORE OFTEN and pay MORE PER TRADE.

┌────────────┬──────────┬─────────────────┬──────────────┐
│            │ Baseline │ Velocity Top-5  │ Improvement  │
├────────────┼──────────┼─────────────────┼──────────────┤
│ Win rate   │ 64.9%    │ 71.7%           │ +6.8%        │
│ Avg P&L    │ $0.60    │ $0.87           │ +44%         │
│ Resolution │ 35.1 days│ 4.7 days        │ 7.5× faster  │
│ ARR        │ +1,130%  │ +6,007%         │ +432%        │
└────────────┴──────────┴─────────────────┴──────────────┘
```

---

### Section 6: The NO Bias — Our Structural Edge

**Plain English summary:**
> "People on prediction markets are optimists. They overbet YES — they want exciting things to happen. This creates a well-documented market inefficiency called the 'favorite-longshot bias.' Contracts priced at 5¢ (implying 5% chance) actually only win 2-4% of the time. We exploit this by systematically betting NO when the market is too optimistic."

#### Visual 6.1: The Favorite-Longshot Bias

**Build as a Recharts bar chart comparing implied vs actual probabilities:**

```
MARKET PRICE vs ACTUAL OUTCOME RATE

        Implied    Actual
 5%  │  █████      ███        Market says 5%, reality is ~3%
10%  │  ██████████ ████████   Market says 10%, reality is ~8%
20%  │  ████████████████████  Close to correct
50%  │  ██████████████████████████████████████████████████  Close
80%  │  ████████████████████████████████████████████████████████  Market UNDER-prices
90%  │  ████████████████████████████████████████████████████████████  Favorites win MORE

     The pattern: cheap contracts (5-20¢) are OVERPRICED.
     That's where our NO bets make money.
```

#### Visual 6.2: YES vs NO Performance

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│   BUY YES                        BUY NO               │
│   Win Rate: 55.8%               Win Rate: 76.2%       │
│   ██████████░░░░░░░░            ████████████████░░░░   │
│                                                        │
│   Threshold: need 15% edge      Threshold: need 5% edge│
│   Kelly: 0.25×                  Kelly: 0.35×           │
│                                                        │
│   "The market is usually        "The market is often   │
│    roughly right about           too optimistic about   │
│    things happening"             unlikely things"       │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

### Section 7: Risk Management — How We Don't Blow Up

**Plain English summary:**
> "The fastest way to lose money isn't bad predictions — it's bad risk management. Our system has multiple layers of protection: position limits, daily loss caps, automatic cooldowns, a kill switch, and real-time monitoring via Telegram. The goal is simple: survive bad streaks so the edge can compound over time."

#### Visual 7.1: Safety Rails Diagram

**Build as a layered shield/onion diagram:**

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 5: KILL SWITCH                                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  LAYER 4: DAILY LOSS LIMIT ($10 → auto halt)         │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  LAYER 3: EXPOSURE CAP (never deploy > 80%)    │  │  │
│  │  │  ┌───────────────────────────────────────────┐  │  │  │
│  │  │  │  LAYER 2: PER-TRADE CAP ($5 max)         │  │  │  │
│  │  │  │  ┌─────────────────────────────────────┐  │  │  │  │
│  │  │  │  │  LAYER 1: KELLY SIZING              │  │  │  │  │
│  │  │  │  │  (math-optimal, quarter-Kelly)      │  │  │  │  │
│  │  │  │  └─────────────────────────────────────┘  │  │  │  │
│  │  │  └───────────────────────────────────────────┘  │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

Additional protections:
• Limit orders ONLY (never overpay)
• Buy at market−1¢ (get filled or miss)
• 60-second order timeout (unfilled → cancel)
• 3-loss cooldown (1 hour pause)
• Telegram alerts on every trade and every error
• Cluster caps: max 15% of bankroll in any one category
```

#### Visual 7.2: Drawdown Controls

```
┌──────────────────────────────────────────────────────┐
│  DRAWDOWN RESPONSE LADDER                            │
│                                                      │
│  0% ████████████████████████████████  Normal trading │
│                                                      │
│ -7% ─────────── DAILY LIMIT ───────── Stop for day  │
│                                                      │
│-15% ████████████████  HALVE all positions            │
│                        (automatic size reduction)    │
│                                                      │
│-25% ████████  HALT ALL TRADING                       │
│               Full model review required             │
│               Human must manually restart            │
│                                                      │
│  The system degrades gracefully. It doesn't go       │
│  from "fine" to "catastrophe" in one step.           │
└──────────────────────────────────────────────────────┘
```

#### Visual 7.3: Gradual Rollout Plan

**Build as a timeline/stepper:**

```
LIVE TRADING ROLLOUT (Starting from $75 seed capital)

WEEK 1                    WEEK 2                    WEEK 3+
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│ Max: $1/trade│          │ Max: $2/trade│          │ Max: $5/trade│
│ 3 trades/day │   ──▶    │ 5 trades/day │   ──▶    │ Unlimited    │
│ Kelly: OFF   │          │ Kelly: OFF   │          │ Kelly: ON    │
│ "Prove the   │          │ "Scale up    │          │ "Full auto   │
│  plumbing"   │          │  carefully"  │          │  if passing" │
└──────────────┘          └──────────────┘          └──────────────┘
```

---

### Section 8: Monte Carlo Simulation — 10,000 Futures

**Plain English summary:**
> "Instead of asking 'what will happen?' we ask 'what are ALL the things that could happen?' We simulate 10,000 different possible futures for our trading system, each with random market outcomes drawn from our backtest statistics. This gives us a distribution of outcomes — best case, worst case, median, and everything in between."

#### Visual 8.1: The Fan Chart (KEY VISUAL — make this large and interactive)

**Build as a Recharts area chart with shaded confidence bands:**

```
MONTE CARLO: 10,000 SIMULATED PORTFOLIO PATHS ($75 start)

$1,100 │                                              ╱╱  95th %ile: $1,054
       │                                           ╱╱╱
$1,000 │                                        ╱╱╱╱
       │                                     ╱╱╱╱╱
  $900 │                                  ╱╱╱╱╱╱╱╱  ── Median: $918
       │                              ╱╱╱╱╱╱╱╱╱
  $800 │                          ╱╱╱╱╱╱╱╱╱╱╱╱╱  5th %ile: $782
       │                     ╱╱╱╱╱╱╱╱╱╱╱╱╱
  $600 │                ╱╱╱╱╱╱╱╱╱╱╱╱╱
       │           ╱╱╱╱╱╱╱╱╱╱╱
  $400 │      ╱╱╱╱╱╱╱╱╱╱
       │ ╱╱╱╱╱╱╱╱
  $200 │╱╱╱╱╱
       │╱╱
   $75 └──────────────────────────────────────────────
       Month 0   2     4     6     8     10    12

█ 5th-95th percentile band (light)
█ 25th-75th percentile band (medium)
━ Median path (bright cyan line)

PROBABILITY OF TOTAL LOSS: 0.0%  ←  Every single path ends positive
```

**Add a toggle button** to switch between "$75 start" and "$10K investor scenario":

```
$10K INVESTOR SCENARIO:
  Median 12-month: $36,907 (+269%)
  5th percentile:  $33,507 (+235%)
  95th percentile: $40,207 (+302%)
  P(loss): 0.0%
```

#### Visual 8.2: How Monte Carlo Works (Animated Explainer)

**Build as a step-by-step visual process:**

```
┌──────────────────────────────────────────────────────────────┐
│  HOW WE SIMULATE 10,000 FUTURES                              │
│                                                              │
│  1. Start with $75                                           │
│                                                              │
│  2. For each day (365 days):                                 │
│     For each trade (5 per day):                              │
│       • Draw a random edge from our distribution             │
│       • Draw YES or NO direction (55.8% / 44.2%)            │
│       • Compute Kelly bet size                               │
│       • Flip a weighted coin (win prob = true prob)          │
│       • Update bankroll                                      │
│                                                              │
│  3. Record the final bankroll                                │
│                                                              │
│  4. Repeat 10,000 times                                      │
│                                                              │
│  5. Look at the distribution of 10,000 final bankrolls       │
│     ┌─────────────────────────────────────────┐              │
│     │                    ███                  │              │
│     │                  ███████                │              │
│     │                ███████████              │              │
│     │              ███████████████            │              │
│     │           ████████████████████          │              │
│     │        ██████████████████████████       │              │
│     │    █████████████████████████████████    │              │
│     └─────────────────────────────────────────┘              │
│     $700    $800    $900   $1,000  $1,100                    │
│                      ↑                                       │
│                   Median: $918                               │
└──────────────────────────────────────────────────────────────┘
```

#### Visual 8.3: Market Impact — Why We Can't Just Scale to Infinity

**Build as a Recharts line chart showing edge erosion:**

```
NET EDGE vs POSITION SIZE (assuming $50K daily market volume)

Edge │
32%  │●────────
     │         ●─────
30%  │                ●─────
     │                      ●────
28%  │                           ●────
     │                                ●──── Edge erodes
26%  │                                      as positions
     │                                      get larger
24%  │
     └──────────────────────────────────────────
     $2    $100   $1K    $5K    $10K   $25K
                  Position Size

┌──────────┬──────────┬──────────────┬───────────┐
│ Position │ Slippage │ Round-Trip   │ Net Edge  │
├──────────┼──────────┼──────────────┼───────────┤
│ $2       │ 0.51%    │ 1.02%        │ 30.7%     │
│ $1,000   │ 0.71%    │ 1.43%        │ 30.3%     │
│ $5,000   │ 0.97%    │ 1.95%        │ 29.8%     │
│ $25,000  │ 1.56%    │ 3.12%        │ 28.6%     │
│ $5.2M    │ —        │ —            │ 0% ← GONE│
└──────────┴──────────┴──────────────┴───────────┘

Strategy capacity ceiling: ~$1-5M practical. Beyond that, our
trades move the market so much that the edge disappears.
```

---

### Section 9: The Research Foundation — What We Know Works (and What Doesn't)

**Plain English summary:**
> "We don't guess about what works. Every technique we use is backed by peer-reviewed academic research. Here's the ranked evidence for what actually improves AI forecasting — and crucially, what HURTS it."

#### Visual 9.1: Evidence Hierarchy — Technique Leaderboard

**Build as a styled leaderboard with green/red coloring:**

```
WHAT ACTUALLY IMPROVES AI PREDICTIONS (ranked by measured impact)

RANK  TECHNIQUE                        BRIER IMPROVEMENT    STATUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 #1   Agentic RAG (web search)         -0.06 to -0.15       📋 Planned
      Let the AI search the web for    ████████████████████
      current information per market

 #2   Platt scaling / calibration      -0.02 to -0.05       ✅ LIVE
      Statistical correction of        █████████████
      overconfidence

 #3   Multi-model ensemble             -0.01 to -0.03       📋 Planned
      Average predictions from         █████████
      3+ different AI models

 #4   Base-rate-first prompting        -0.011 to -0.014     ✅ LIVE
      Start reasoning from             ████
      historical frequency

 #5   Structured scratchpad            -0.005 to -0.010     ✅ LIVE
      Step-by-step reasoning           ███

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 ❌   TECHNIQUES THAT HURT PREDICTIONS (DO NOT USE)

      Bayesian reasoning prompts       +0.005 to +0.015 WORSE
      "Think like a superforecaster"   ~0 effect (useless)
      Narrative framing                HARMFUL
      Propose-Evaluate-Select          HARMFUL
```

#### Visual 9.2: Where We Are vs The Frontier

**Build as a horizontal scale/gauge:**

```
BRIER SCORE SCALE (lower = better)

0.00          0.08    0.10       0.19    0.24  0.25      0.36
 │             │       │          │       │     │          │
 ▼             ▼       ▼          ▼       ▼     ▼          ▼
Perfect    Superforecasters  Foresight-32B  US   Random  LLM without
           (human experts)   (fine-tuned)   ↑   chance   search
                                            │
                                         OUR SYSTEM
                                         (0.245 calibrated)

ROOM FOR IMPROVEMENT:
• Adding web search (RAG): could reach ~0.10-0.15
• Adding ensemble:          could reach ~0.15-0.20
• Both combined:            could approach ~0.08-0.10
• That would put us at superforecaster level.
```

#### Visual 9.3: Key Research Papers

**Build as expandable cards with paper title, finding, and citation:**

Display 10 key papers with one-line findings:
1. **Schoenegger 2025** — 38 prompts tested, only base-rate-first works
2. **Halawi et al. (NeurIPS 2024)** — LLM ensembles match human crowds
3. **Lu 2025, RAND** — Category routing matters; politics best, crypto zero
4. **Bridgewater AIA Forecaster 2025** — Search + calibration = superforecaster parity
5. **ForecastBench (Karger 2025)** — LLM-superforecaster parity projected Nov 2026
6. **Clinton & Huang 2025** — Polymarket political markets only ~67% correct
7. **Lou & Sun 2024** — LLMs copy market prices with 0.994 correlation when shown them
8. **Whelan 2025, Becker 2025** — Favorite-longshot bias documented on Polymarket
9. **Lightning Rod Labs** — Fine-tuned 32B model beats frontier models on forecasting
10. **Xiong et al. (ICLR 2024)** — Two-step confidence elicitation improves calibration

---

### Section 10: Roadmap — Where We're Going & Where Resources Go

**Plain English summary:**
> "Here's what we've built, what we're building next, and where we're investing our time, compute, and money. Every item is prioritized by expected impact on returns."

#### Visual 10.1: What's Done, What's Next

**Build as a Kanban-style board or roadmap timeline:**

```
✅ COMPLETED                    🔄 IN PROGRESS              📋 NEXT UP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Anti-anchoring prompt ✅        Paper→live transition 🔄     Agentic RAG pipeline 📋
532-market backtest ✅          Gradual rollout 🔄           Multi-model ensemble 📋
Platt scaling calibration ✅    Live perf validation 🔄      Weather multi-model 📋
Quarter-Kelly sizing ✅                                      Market-making strategy 📋
Asymmetric NO thresholds ✅                                  LLM+market consensus 📋
Category routing ✅                                          News sentiment pipeline 📋
Capital velocity optimizer ✅                                Foresight-32B eval 📋
Safety rails + kill switch ✅                                Social sentiment 📋
Ensemble skeleton ✅                                         Cross-platform monitoring 📋
Monte Carlo simulation ✅                                    Category-specific calibration 📋
Risk framework ✅
Resolution rule playbook ✅
```

#### Visual 10.2: Resource Allocation — Where the Effort Goes

**Build as a treemap or proportional area chart:**

```
RESOURCE ALLOCATION BY EXPECTED IMPACT

┌───────────────────────────────────────────────────────┐
│                                                       │
│     AGENTIC RAG (WEB SEARCH)                         │
│     Expected Brier improvement: -0.06 to -0.15       │
│     Status: P0 — Next major project                  │
│     Cost: API fees for search + news providers       │
│     Impact: TRANSFORMATIVE — biggest single upgrade   │
│                                                       │
├───────────────────────┬───────────────────────────────┤
│                       │                               │
│  MULTI-MODEL          │  MARKET-MAKING STRATEGY       │
│  ENSEMBLE             │  Expected: zero-fee execution │
│  Brier: -0.01 to     │  Status: P1 research phase    │
│  -0.03                │  Impact: Eliminate taker fees  │
│  Status: P1           │  entirely (maker rebates)     │
│  Cost: GPT + Grok API │                               │
│                       │                               │
├───────────┬───────────┼───────────────────────────────┤
│           │           │                               │
│ WEATHER   │ NEWS      │  LIVE TRADING VALIDATION      │
│ MULTI-    │ SENTIMENT │  Status: In progress          │
│ MODEL     │ PIPELINE  │  Cost: $75 seed capital       │
│ P1        │ P1        │  Impact: Proves the system    │
│           │           │                               │
├───────────┴───────────┼───────────────────────────────┤
│                       │                               │
│ FORESIGHT-32B EVAL    │ CONTINUOUS IMPROVEMENT        │
│ Fine-tuned forecasting│ Auto-recalibration            │
│ model evaluation      │ Feedback loops                │
│ P2                    │ Self-improving architecture   │
│                       │ P2                            │
└───────────────────────┴───────────────────────────────┘
```

#### Visual 10.3: The Path to Superforecaster-Level AI

**Build as a stepped progression:**

```
THE IMPROVEMENT ROADMAP (Brier Score)

0.245  ──▶  ~0.20  ──▶  ~0.15  ──▶  ~0.10  ──▶  0.08
 NOW        +Ensemble    +RAG        +Market      SUPERFORECASTER
            (3 models)   (web search) Consensus   PARITY
            Q2 2026      Q3 2026     Q4 2026      2027 target

Each step compounds with the others.
At 0.10 Brier, our edge roughly DOUBLES from current levels.
```

---

### Section 11: Strategy Comparison — The Full Backtest

**Build as an interactive, sortable data table:**

```
STRATEGY VARIANTS (532 markets, all backtested)

┌──────────────────────────────┬────────┬───────┬────────┬───────┬────────┬──────────┐
│ Strategy                     │Win Rate│Trades │Net P&L │ Brier │ Sharpe │ARR @5/day│
├──────────────────────────────┼────────┼───────┼────────┼───────┼────────┼──────────┤
│ Baseline (5% symmetric)      │ 64.9%  │  470  │$275.30 │0.2391 │ 10.89  │ +1,086%  │
│ NO-only                      │ 76.2%  │  210  │$217.90 │0.2391 │ 21.62  │ +2,170%  │
│ Calibrated (5% symmetric)    │ 68.5%  │  372  │$272.28 │0.2171 │ 13.99  │ +1,437%  │
│ Calibrated + Asymmetric      │ 68.6%  │  354  │$260.46 │0.2171 │ 14.07  │ +1,446%  │
│ Calibrated + NO-only         │ 70.2%  │  282  │$225.18 │0.2171 │ 15.49  │ +1,596%  │
│ ★ Cal+CatFilter+Asym        │ 71.2%  │  264  │$221.36 │0.2138 │ 16.43  │ +6,007%  │
│ Cal+Asym+Conf+CatFilter     │ 71.2%  │  264  │$219.68 │0.2138 │ 17.01  │ +1,677%  │
│ High Threshold (10% sym)     │ 65.3%  │  426  │$255.74 │0.2391 │ 11.19  │ +1,121%  │
└──────────────────────────────┴────────┴───────┴────────┴───────┴────────┴──────────┘

★ = Current production strategy
Highlight the best-variant row with a cyan border.
```

---

### Section 12: The Bot Architecture — Under the Hood

**Plain English summary:**
> "The bot runs on a $10/month cloud server in Frankfurt, Germany. Every 5 minutes, it wakes up, scans 100 markets, runs the AI on promising ones, and executes trades. Here's exactly how it works."

#### Visual 12.1: System Architecture Diagram

**Build as an animated flow diagram with boxes and arrows:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SYSTEM ARCHITECTURE                          │
│                                                                     │
│  ┌──────────┐    ┌───────────┐    ┌──────────────┐                 │
│  │ POLYMARKET│    │ NOAA      │    │ NEWS APIs    │                 │
│  │ Gamma API │    │ Weather   │    │ (planned)    │                 │
│  └─────┬─────┘    └─────┬─────┘    └──────┬───────┘                 │
│        │                │                 │                         │
│        ▼                ▼                 ▼                         │
│  ┌─────────────────────────────────────────────┐                   │
│  │              SCANNER + FILTER                │                   │
│  │  100 markets/cycle → ~18 with signal         │                   │
│  └──────────────────────┬──────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌─────────────────────────────────────────────┐                   │
│  │           CLAUDE AI ESTIMATOR                │                   │
│  │  Anti-anchoring prompt (no market price)     │                   │
│  │  6-step reasoning → raw probability          │                   │
│  │  Platt scaling → calibrated probability      │                   │
│  │  Category routing → skip low-edge markets    │                   │
│  └──────────────────────┬──────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌─────────────────────────────────────────────┐                   │
│  │          POSITION SIZING ENGINE              │                   │
│  │  Quarter-Kelly with asymmetric NO bias       │                   │
│  │  Velocity scoring → prioritize fast markets  │                   │
│  │  Caps: $5/trade, 80% exposure, cluster limits│                   │
│  └──────────────────────┬──────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────┐             │
│  │ PAPER BROKER  │  │ LIVE BROKER  │  │ SAFETY RAILS│             │
│  │ (current)     │  │ (ready)      │  │ Kill switch │             │
│  │ Simulated     │  │ Real USDC    │  │ Loss limits │             │
│  │ fills         │  │ on Polygon   │  │ Cooldowns   │             │
│  └───────┬───────┘  └──────┬───────┘  └──────┬──────┘             │
│          │                 │                  │                     │
│          ▼                 ▼                  ▼                     │
│  ┌─────────────────────────────────────────────┐                   │
│  │         MONITORING + REPORTING               │                   │
│  │  Telegram alerts  │  SQLite DB  │  JSON logs  │                   │
│  │  FastAPI dashboard │  Metrics   │  Risk events │                   │
│  └─────────────────────────────────────────────┘                   │
│                                                                     │
│  Server: DigitalOcean Frankfurt │ Cost: ~$10/month                  │
│  Scan interval: 5 minutes       │ Language: Python                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

### Section 13: Honest Risk Assessment

**Build as a card grid with severity indicators and full explanations:**

### Risk Cards (15 Critical Risks)

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | **Backtest ≠ Live Performance** | 🔴 HIGH | Gradual rollout ($1→$2→$5/trade), 32% confidence disclosure |
| 2 | **Edge Decay (Competition)** | 🔴 HIGH | Market making mode (zero fees), continuous research, data feed expansion |
| 3 | **Polymarket Platform Risk** | 🔴 HIGH | ToS changes, fee increases, API deprecation — diversify to other platforms |
| 4 | **LLM Reliability** | 🟡 MEDIUM | Multi-model ensemble (Claude + GPT + Grok), fallback to historical base rates |
| 5 | **Calibration Drift** | 🟡 MEDIUM | Continuous backtest validation, auto-retrain on new data |
| 6 | **Liquidity Risk** | 🟡 MEDIUM | Min $100 liquidity filter, participation rate caps, order book depth modeling |
| 7 | **API Rate Limiting** | 🟡 MEDIUM | Exponential backoff, request queuing, multiple API key rotation |
| 8 | **Smart Contract Risk** | 🟡 MEDIUM | Only trade established markets, monitor for resolution disputes |
| 9 | **Regulatory Risk** | 🟡 MEDIUM | Reg D 506(b) compliance, CFTC Rule 4.13 exemption, legal review |
| 10 | **Key Person Risk** | 🟡 MEDIUM | Full documentation (Command Node), automated operation, kill switch |
| 11 | **VPS Downtime** | 🟢 LOW | Systemd auto-restart, DigitalOcean 99.99% SLA, monitoring alerts |
| 12 | **Database Corruption** | 🟢 LOW | Daily backups, WAL mode SQLite, PostgreSQL migration path |
| 13 | **Telegram Bot Failure** | 🟢 LOW | Non-critical path, dashboard fallback, email alerts planned |
| 14 | **Capital Concentration** | 🟢 LOW | Category haircuts (50% above 3 positions), 80% max exposure |
| 15 | **Crypto Market Contagion** | 🟢 LOW | Crypto/Sports categories excluded (Priority 0), USDC stability monitor |

---

### Section 14: Competitive Landscape

**Known Competitors:**

| Competitor | All-Time P&L | Strategy | Our Edge |
|-----------|-------------|----------|----------|
| **Fredi9999** | $16.62M | High-frequency market making | AI forecasting vs pure MM |
| **OpenClaw** | $1.7M (20K trades) | Automated trading bot | Category specialization |
| **Poly-Maker** | Unknown | Open-source market maker | Proprietary calibration |
| **Polymarket Agents** | Unknown | LLM-based forecasting | Platt scaling + asymmetric sizing |
| **discountry** | Unknown | Open-source framework | Full-stack integration |

**Estimated Bot Ecosystem:** 50-100 automated traders, tens of millions USD under management

**Our Differentiators:**
1. **AI Forecasting** — Claude Haiku with anti-anchoring + Platt calibration (not just market making)
2. **Category Routing** — Avoid crypto/sports (no edge), focus on politics/weather (highest edge)
3. **Asymmetric NO-Bias** — Exploit favorite-longshot effect (76% NO win rate vs 56% YES)
4. **Safety-First** — 6-layer risk management, institutional-grade controls
5. **Research-Backed** — 12+ academic papers, superforecaster methodology

---

### Section 15: Veteran Impact — Where the Money Goes

**Plain English summary:**
> "We're not just picking charities at random. We're applying the same data-driven approach we use for trading to figure out which veteran nonprofits deliver the most impact per dollar. Here's what we know so far — and what we're actively researching."

#### Visual 15.1: The Veteran Crisis (by the numbers)

**Build as a sobering, clean infographic section (muted tones, respectful):**

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   ~17 veterans die by suicide every day in the US               │
│                                                                  │
│   ~6,000+ veteran suicides per year                             │
│                                                                  │
│   Veterans are 1.5× more likely to die by suicide               │
│   than non-veteran adults                                       │
│                                                                  │
│   30% of post-9/11 veterans report a mental health condition    │
│                                                                  │
│   Only ~50% of veterans who need mental health care seek it     │
│                                                                  │
│   These numbers are why this project exists.                    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Note to builder:** These statistics should be verified and sourced. Display sources (VA data, SAMHSA, etc.) in small text below.

#### Visual 15.2: Highest-Leverage Veteran Nonprofits (Research In Progress)

**Build as a card grid that will be populated as research completes:**

```
┌──────────────────────────────────────────────────────────────────┐
│  NONPROFIT EVALUATION CRITERIA                                   │
│                                                                  │
│  We evaluate veteran nonprofits on:                             │
│                                                                  │
│  1. Cost per veteran served (efficiency)                        │
│  2. Suicide prevention outcomes (measured impact)               │
│  3. Mental health program quality (evidence-based treatments)   │
│  4. Physical health programs (TBI, chronic pain, rehabilitation)│
│  5. Transparency & accountability (financial reporting)         │
│  6. Scalability (can more funding = more impact?)              │
│                                                                  │
│  We're running deep research to identify the top organizations  │
│  and will publish our findings here.                            │
│                                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ Organization │ │ Organization │ │ Organization │            │
│  │ #1           │ │ #2           │ │ #3           │            │
│  │              │ │              │ │              │            │
│  │ 🔍 Research  │ │ 🔍 Research  │ │ 🔍 Research  │            │
│  │ in progress  │ │ in progress  │ │ in progress  │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│                                                                  │
│  Want to help with this research? Grab a prompt from the        │
│  queue above and run it in ChatGPT Deep Research.               │
└──────────────────────────────────────────────────────────────────┘
```

---

### Section 16: Corporate Sponsors & Partners

**Build as a clean sponsor grid with the Replit logo featured prominently:**

```
┌──────────────────────────────────────────────────────────────────┐
│  BUILT WITH SUPPORT FROM                                         │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                                                            │  │
│  │                     [REPLIT LOGO]                          │  │
│  │                                                            │  │
│  │  Infrastructure & Hosting Partner                         │  │
│  │  This project is built and deployed on Replit.            │  │
│  │  Replit provides the development environment, hosting,    │  │
│  │  and deployment infrastructure that makes this possible.  │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ [ANTHROPIC LOGO] │  │ [OPENAI LOGO]    │                     │
│  │ Claude AI        │  │ GPT (Ensemble)   │                     │
│  │ Core estimation  │  │ Planned ensemble │                     │
│  │ engine           │  │ member           │                     │
│  └──────────────────┘  └──────────────────┘                     │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ [DIGITALOCEAN]   │  │ YOUR LOGO HERE   │                     │
│  │ VPS hosting      │  │                  │                     │
│  │ Bot runtime      │  │ Interested in    │                     │
│  │                  │  │ sponsoring?      │                     │
│  │                  │  │ Contact us.      │                     │
│  └──────────────────┘  └──────────────────┘                     │
│                                                                  │
│  Interested in corporate sponsorship? 100% of sponsorship       │
│  funds go to veteran mental health nonprofits. Your brand       │
│  gets featured here and in all project communications.          │
│  Contact: [email/form]                                          │
└──────────────────────────────────────────────────────────────────┘
```

---

### Section 17: Footer / Disclaimer

**Full-width footer with disclaimer:**

> **Disclaimer:** All performance figures presented on this page are from backtesting against historical data and do not represent live trading results. Past performance, whether simulated or actual, does not guarantee future results. Prediction market trading involves substantial risk of loss. This page is for informational and educational purposes only. It does not constitute financial advice or an offer to sell securities. The system described is experimental and unproven in live markets. You should only trade with money you can afford to lose entirely.

---

## Technical Implementation Notes

### Static Data Architecture

ALL data should be embedded as TypeScript constants. No API calls for backtest data.

```typescript
// data/constants.ts

// THE NUMBER — the single most important metric on the entire site
// Everything else is context for this number
export const THE_NUMBER = {
  arr_current: 6007,           // +6,007% — THE NUMBER shown on the hero
  arr_conservative: 124,       // +124% — Conservative floor (Baseline, 3/day)
  arr_moderate: 403,           // +403% — Moderate (Cal+CatFilter+Asym, 5/day)
  arr_aggressive: 872,         // +872% — Aggressive (NO-only, 8/day)
  arr_velocity_max: 6007,      // +6,007% — Velocity-optimized (top-5, fast markets)
  confidence_score: 32,        // 0-100 editorial estimate (lower for aggressive target)
  label: 'Simulated Annual Return',
  caveat: 'Velocity-optimized · Backtested on 532 markets · Not live trading',
};

export const CAPITAL_DEPLOYMENT = {
  seed_capital: 2000,          // $2K starting capital
  weekly_add: 1000,            // $1K/week additional
  risk_posture: 'aggressive',  // maximize expected velocity, not safety
  kelly_target: 'full',        // full Kelly or higher on velocity trades
  velocity_priority: true,     // always take highest-velocity signals first
};

export const KEY_METRICS = {
  markets_tested: 532,
  win_rate_calibrated: 0.685,
  best_variant_win_rate: 0.712,
  best_variant_sharpe: 16.43,
  brier_calibrated_oos: 0.2451,
  buy_yes_win_rate: 0.558,
  buy_no_win_rate: 0.762,
  avg_pnl_per_trade: 0.60,
  avg_net_pnl_best: 0.84,     // best variant avg net P&L/trade
  avg_edge: 0.317,
  mc_simulations: 10000,
  mc_p_loss: 0,
  mc_median_75: 918,
  mc_p5_75: 782,
  mc_p95_75: 1054,
  mc_median_10k: 36907,
  starting_capital: 75,
  total_capital_at_risk: 315,  // $75 capital + $240 annual infra
  kelly_fraction: 0.25,
  platt_a: 0.5914,
  platt_b: -0.3977,
  velocity_win_rate: 0.717,
  velocity_arr_improvement: 432,
  strategy_capacity_max: 5_000_000,
};

export const STRATEGY_COMPARISON = [
  { name: 'Baseline (5% symmetric)', winRate: 0.649, trades: 470, netPnl: 275.30, brier: 0.2391, sharpe: 10.89, arr: 1086, highlight: false },
  { name: 'NO-only', winRate: 0.762, trades: 210, netPnl: 217.90, brier: 0.2391, sharpe: 21.62, arr: 2170, highlight: false },
  { name: 'Calibrated (5% symmetric)', winRate: 0.685, trades: 372, netPnl: 272.28, brier: 0.2171, sharpe: 13.99, arr: 1437, highlight: false },
  { name: 'Calibrated + Asymmetric', winRate: 0.686, trades: 354, netPnl: 260.46, brier: 0.2171, sharpe: 14.07, arr: 1446, highlight: false },
  { name: 'Calibrated + NO-only', winRate: 0.702, trades: 282, netPnl: 225.18, brier: 0.2171, sharpe: 15.49, arr: 1596, highlight: false },
  { name: 'Cal + CatFilter + Asym', winRate: 0.712, trades: 264, netPnl: 221.36, brier: 0.2138, sharpe: 16.43, arr: 1692, highlight: true },
  { name: 'Cal + Asym + Conf + CatFilter', winRate: 0.712, trades: 264, netPnl: 219.68, brier: 0.2138, sharpe: 17.01, arr: 1677, highlight: false },
  { name: 'High Threshold (10% sym)', winRate: 0.653, trades: 426, netPnl: 255.74, brier: 0.2391, sharpe: 11.19, arr: 1121, highlight: false },
];

export const CALIBRATION_MAP = [
  { raw: 0.05, calibrated: 0.105, direction: 'Pulled up' },
  { raw: 0.20, calibrated: 0.228, direction: '~correct' },
  { raw: 0.50, calibrated: 0.402, direction: 'Pulled down' },
  { raw: 0.70, calibrated: 0.526, direction: 'Pulled down significantly' },
  { raw: 0.90, calibrated: 0.711, direction: 'Major correction' },
  { raw: 0.95, calibrated: 0.793, direction: 'Major correction' },
];

export const VELOCITY_BUCKETS = [
  { bucket: '<24h', trades: 111, winRate: 0.721, avgPnl: 0.88 },
  { bucket: '1-3 days', trades: 11, winRate: 0.818, avgPnl: 1.27 },
  { bucket: '1-4 weeks', trades: 264, winRate: 0.599, avgPnl: 0.39 },
  { bucket: '>1 month', trades: 84, winRate: 0.690, avgPnl: 0.76 },
];

export const KELLY_COMPARISON = [
  { fraction: 'Full (1×)', growth: '~10¹⁶×', p50dd: 1.00, ruinRisk: 0.369, sharpe: 0.37 },
  { fraction: 'Half (0.5×)', growth: '~10¹¹×', p50dd: 0.947, ruinRisk: 0, sharpe: 0.57 },
  { fraction: 'Quarter (0.25×)', growth: '~10⁶×', p50dd: 0.08, ruinRisk: 0, sharpe: 0.64, current: true },
  { fraction: 'Tenth (0.1×)', growth: '~10²×', p50dd: 0, ruinRisk: 0, sharpe: 0.68 },
];

export const MARKET_IMPACT = [
  { size: 2, slippage: 0.0051, roundTrip: 0.0102, netEdge: 0.307 },
  { size: 100, slippage: 0.0057, roundTrip: 0.0113, netEdge: 0.306 },
  { size: 1000, slippage: 0.0071, roundTrip: 0.0143, netEdge: 0.303 },
  { size: 5000, slippage: 0.0097, roundTrip: 0.0195, netEdge: 0.298 },
  { size: 10000, slippage: 0.0121, roundTrip: 0.0242, netEdge: 0.293 },
  { size: 25000, slippage: 0.0156, roundTrip: 0.0312, netEdge: 0.286 },
];

export const EVIDENCE_HIERARCHY = [
  { rank: 1, technique: 'Agentic RAG (web search)', brierDelta: '-0.06 to -0.15', source: 'AIA Forecaster (Bridgewater, 2025)', status: 'planned' },
  { rank: 2, technique: 'Platt scaling / calibration', brierDelta: '-0.02 to -0.05', source: 'AIA Forecaster (2025)', status: 'live' },
  { rank: 3, technique: 'Multi-model ensemble', brierDelta: '-0.01 to -0.03', source: 'Halawi et al. (NeurIPS, 2024)', status: 'planned' },
  { rank: 4, technique: 'Base-rate-first prompting', brierDelta: '-0.011 to -0.014', source: 'Schoenegger et al. (2025)', status: 'live' },
  { rank: 5, technique: 'Structured scratchpad', brierDelta: '-0.005 to -0.010', source: 'Halawi (2024), Lu (2025)', status: 'live' },
];

export const HARMFUL_TECHNIQUES = [
  { technique: 'Bayesian reasoning prompts', impact: '+0.005 to +0.015 WORSE', source: 'Schoenegger (2025)' },
  { technique: '"Think like a superforecaster"', impact: '~0 effect (useless)', source: 'Schoenegger (2025)' },
  { technique: 'Narrative framing', impact: 'HARMFUL', source: 'Lu (2025)' },
  { technique: 'Propose-Evaluate-Select', impact: 'HARMFUL', source: 'Schoenegger (2025)' },
];

export const RISKS = [
  { severity: 'critical', title: 'Backtest ≠ Live', description: 'All numbers are simulated. Zero live trades have resolved. Real markets have slippage, partial fills, and competitors that backtests don\'t capture.' },
  { severity: 'critical', title: 'AI Is Barely Better Than Random', description: 'Our Brier score (0.245) barely beats coin-flipping (0.25). The edge is real but thin.' },
  { severity: 'moderate', title: 'Competitive Pressure', description: 'Bots like OpenClaw have made $1.7M. Only 0.5% of Polymarket users earn >$1K. Most profitable bots use arbitrage, not forecasting.' },
  { severity: 'moderate', title: 'NO-Bias May Erode', description: 'Our 76% NO win rate exploits a structural inefficiency that could shrink as more AI traders enter.' },
  { severity: 'moderate', title: 'Platform Risk', description: 'Polymarket is crypto-based, has CFTC history, and is adding fees.' },
  { severity: 'low', title: 'Capital Concentration', description: 'Mitigated by cluster caps (15% max per category).' },
  { severity: 'low', title: 'Resolution Timing', description: 'Mitigated by velocity optimization (+432% ARR improvement).' },
  { severity: 'low', title: 'Infrastructure Cost', description: '~$20/month. Minimal operational risk.' },
];
```

### Scroll-Spy Sidebar TOC

The sidebar should list all 15 sections with nested subsections. Current section highlights as you scroll. Clicking a section smooth-scrolls to it.

```
Table of Contents
─────────────────
0. Hero (The Formula)
1. The Mission — Why We Do This
   1.0 Mission Statement
   1.1 How the Money Flows
   1.2 How Anyone Can Contribute
   (Prompt Queue / LLM Token Donation)
2. The Big Picture
   2.1 Core Loop
   2.2 What Is a Prediction Market?
   2.3 Human + Bot Partnership
3. The AI Brain
   3.1 Anchoring Problem
   3.2 6-Step Reasoning
   3.3 Category Routing
4. Calibration
   4.1 Overconfidence Problem
   4.2 Correction Map
   4.3 Validation
5. Position Sizing
   5.1 Kelly Criterion
   5.2 Why Quarter-Kelly
   5.3 Asymmetric Sizing
   5.4 Kelly vs Flat Betting
6. Capital Velocity
7. The NO Bias
8. Risk Management
   8.1 Safety Rails
   8.2 Drawdown Controls
   8.3 Rollout Plan
9. Monte Carlo Simulation
   9.1 Fan Chart
   9.2 How It Works
   9.3 Market Impact
10. Research Foundation
    10.1 Evidence Hierarchy
    10.2 Frontier Comparison
    10.3 Key Papers
11. Roadmap & Resources
12. Strategy Comparison
13. Bot Architecture
14. Risk Assessment
15. Competitive Landscape
16. Veteran Impact
17. Corporate Sponsors
18. Disclaimer
```

### Component Library

Use shadcn/ui components throughout:
- `Card` for all data panels
- `Table` for data tables (with sorting via `@tanstack/react-table`)
- `Badge` for status indicators (Live, Planned, etc.)
- `Accordion` for expandable research paper cards
- `Tooltip` for metric definitions on hover
- `Progress` for Brier score comparisons

### Chart Library

Use Recharts for all visualizations:
- `AreaChart` for Monte Carlo fan chart
- `BarChart` for velocity buckets, strategy comparison
- `ScatterChart` for anchoring before/after
- `LineChart` for Kelly growth curve, market impact

### Animations

Use Framer Motion:
- `useInView` for scroll-triggered animations
- Counter animation for hero metrics (count up from 0)
- `AnimatePresence` for expandable sections
- Subtle fade-up for each section as you scroll to it

### Print/PDF Support

Add a `@media print` stylesheet that:
- Removes the sidebar TOC
- Removes animations
- Forces all sections to display (no accordion collapsing)
- Uses white background with dark text
- Adds page breaks before each major section
- Includes the URL in the footer of each printed page

### Performance

- Static generation (SSG) — no server-side rendering needed
- All data is hardcoded constants
- Lazy-load charts below the fold with `React.lazy` + `Suspense`
- Image optimization for any screenshots
- Bundle split per section if needed

### SEO

```html
<title>Predictive Alpha Fund — Open-Source AI Prediction Market Trading System</title>
<meta name="description" content="A complete walkthrough of an AI-powered Polymarket trading system. 68.5% win rate on 532 backtested markets. Open methodology, real data, transparent risks." />
```

---

## Summary of Sections (Relationship to THE NUMBER)

| # | Section | Tag | Purpose | Key Visual |
|---|---------|-----|---------|-----------|
| 0 | Hero | — | +403% ARR top and center, personal story, formula | THE NUMBER, confidence meter, scenario strip |
| 1 | The Mission | 💜 Where it goes | Why we do this — veteran cause + money flow + contribute model | Sankey flow, prompt queue, vision manifesto |
| 2 | Big Picture | 📐 How we get to +6,007% | What we do in plain English | Core loop diagram, prediction market example |
| 3 | AI Brain | 📐 How we get to +6,007% | How probability estimation works | Anchoring scatter plots, 6-step stepper |
| 4 | Calibration | ✅ Why you should believe it | Fixing overconfidence | Reliability diagram, correction map |
| 5 | Position Sizing | 📐 How we get to +6,007% | How much to bet | Kelly curve chart, backtest comparison |
| 6 | Capital Velocity | 📈 How we improve it | Speed multiplier | Velocity bar chart, before/after table |
| 7 | NO Bias | ✅ Why you should believe it | Structural market inefficiency | Favorite-longshot chart, YES vs NO |
| 8 | Risk Management | ✅ Why you should believe it | How we don't blow up | Safety layer diagram, drawdown ladder |
| 9 | Monte Carlo | ✅ Why you should believe it | Simulating 10,000 futures | Fan chart, histogram, impact table |
| 10 | Research | ✅ Why you should believe it | Academic evidence base | Evidence leaderboard, frontier gauge |
| 11 | Roadmap | 📈 How we improve it | Where resources go next | Kanban board, treemap, improvement path |
| 12 | Strategy Comparison | 📐 How we get to +6,007% | Full backtest results | Sortable data table |
| 13 | Architecture | 📐 How we get to +6,007% | Technical system diagram | Flow diagram |
| 14 | Risk Assessment | ⚠️ Why you should be skeptical | Honest risk cards | Severity-coded card grid |
| 15 | Competitive Landscape | ⚠️ Why you should be skeptical | Who else is playing | Competitor table |
| 16 | Veteran Impact | 💜 Where it goes | Where the money goes + nonprofit research | Crisis stats, eval grid |
| 17 | Corporate Sponsors | 💜 Where it goes | Replit + partners | Sponsor logo grid |
| 18 | Disclaimer | ⚠️ Why you should be skeptical | Legal CYA | Footer text |

---

This document is the complete build specification. Every section has visual mockups, all data is specified, and the technical implementation is detailed. A developer should be able to build the entire page from this document alone.
