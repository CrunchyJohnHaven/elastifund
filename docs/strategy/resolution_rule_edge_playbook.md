# Resolution Rule Edge Playbook

**Purpose:** Systematically identify prediction markets where traders misunderstand resolution criteria, and trade them profitably without taking unacceptable dispute or time-to-cash risk.

**Core principle:** The edge is not in predicting the event — it's in reading the rules more carefully than the market does.

---

## 1. Ambiguity Scanning Checklist

Run this checklist against every market's resolution criteria before sizing a position. Each "Yes" is a flag — not necessarily a no-trade, but a factor that must be scored.

### 1.1 Source & Oracle

- [ ] Is the resolution source explicitly named (e.g., "per AP call," "per BLS release")?
- [ ] If multiple sources could apply, does the rule specify a tiebreaker or hierarchy?
- [ ] Has this oracle/source changed methodology recently or announced upcoming changes?
- [ ] Could the source retract, revise, or delay publication?
- [ ] Is there a fallback source if the primary is unavailable?
- [ ] Does the platform reserve discretion to override the named source?

### 1.2 Temporal Boundaries

- [ ] Is the resolution date/time stated with a timezone?
- [ ] Are "end of day," "close of business," or "by [date]" terms defined?
- [ ] If the event spans time zones (e.g., election night), is the cutoff explicit?
- [ ] Is there a distinction between "announced by" and "effective as of"?
- [ ] Does the rule account for delays, recounts, or revised data?
- [ ] Is there a maximum resolution window (e.g., "resolved within 30 days of expiry")?

### 1.3 Definitional Precision

- [ ] Are key terms defined (e.g., "recession," "ceasefire," "announce")?
- [ ] Could a reasonable person read the same rule and reach a different outcome?
- [ ] Does the rule use hedging language ("generally," "typically," "in most cases")?
- [ ] Are thresholds exact (e.g., ">100" vs. "around 100" vs. "at least 100")?
- [ ] Is the unit of measurement specified (nominal vs. real, seasonally adjusted vs. not)?
- [ ] For binary markets: is there a clear, testable condition that maps to Yes/No?

### 1.4 Edge Cases & Conditionality

- [ ] What happens if the event is cancelled, postponed, or rendered moot?
- [ ] Is partial fulfillment addressed (e.g., "peace deal" that covers only part of a conflict)?
- [ ] Does the rule handle successor entities (mergers, name changes, regime changes)?
- [ ] Are force-majeure / extraordinary-event clauses present?
- [ ] If resolution depends on a human judgment call (e.g., "did X say Y"), is the standard defined?

### 1.5 Platform-Specific Mechanics

- [ ] Does the platform have an appeals or dispute process? What are its timelines?
- [ ] Can the platform unilaterally void or N/A a market?
- [ ] Has this platform historically resolved ambiguous markets in a consistent direction?
- [ ] Are there fee or liquidity consequences if resolution is delayed?

---

## 2. Rule-Risk Taxonomy

Every ambiguity falls into one of six categories. Categorize each flag from the checklist, because category determines the likely failure mode and the appropriate hedge.

### Category A — Source Ambiguity

**What it is:** The resolution source is missing, vague, or multiple valid sources could yield different outcomes.

**Example:** "Resolves Yes if unemployment rises above 5%." — Per which release? Preliminary or revised? U-3 or U-6? BLS or a different agency?

**Failure mode:** Market resolves on a source you didn't model, or resolution is delayed while the platform picks a source.

**Typical edge:** When the market prices one interpretation but the rules technically support another, and precedent on this platform favors the technically correct reading.

### Category B — Timezone & Temporal Gaps

**What it is:** Resolution depends on a time boundary that is unspecified or ambiguous.

**Example:** "Resolves Yes if the deal closes by March 31." — UTC? Eastern? Market close? End of calendar day?

**Failure mode:** You're right on the substance but wrong on the cutoff, or the event lands in the gap between interpretations.

**Typical edge:** When an event is virtually certain to occur but timing is tight, and the market is discounting because retail traders assume the tighter interpretation.

### Category C — Wording Traps

**What it is:** The rule uses natural language that a careful reader interprets differently from a casual reader.

**Example:** "Will X announce a candidacy?" — Does a social media post count? Does an exploratory committee count? The careful reader checks whether "announce" requires a formal filing; the casual reader assumes any public statement qualifies.

**Failure mode:** You trade on the casual reading and the platform resolves on the strict reading, or vice versa.

**Typical edge:** Largest edge category. Most traders skim rules. If you parse them like a contract, you often find the technically correct resolution differs from the "obvious" one.

### Category D — Multi-Source Conflict

**What it is:** Two or more authoritative sources give different answers, and the rule doesn't specify which wins.

**Example:** "Resolves per the official election results." — What if the election commission and the courts give different answers at different times?

**Failure mode:** Extended resolution delay while the platform waits for clarity, locking up capital.

**Typical edge:** Usually not tradeable for edge — better to avoid unless the pricing is extreme enough to compensate for capital lockup.

### Category E — Revision & Retroaction Risk

**What it is:** The data used for resolution is subject to revision after initial publication.

**Example:** GDP figures are revised multiple times. If the market says "Q4 GDP growth above 2%," the advance estimate might say 2.1% and the final revision says 1.9%.

**Failure mode:** Market resolves on preliminary data, you modeled final data (or vice versa). Or, resolution is contested because revisions crossed the threshold.

**Typical edge:** When you know the platform's historical practice (e.g., always uses first release) and the market is pricing as if revisions matter.

### Category F — Platform Discretion & Governance

**What it is:** The platform retains the right to override, void, or reinterpret rules.

**Example:** "In the event of ambiguity, the resolution committee will determine the outcome."

**Failure mode:** You have the technically correct read, but the platform exercises discretion against you. No recourse.

**Typical edge:** Generally negative edge — avoid unless you have strong precedent data showing the platform exercises discretion predictably.

---

## 3. Scoring System: Edge × Dispute Probability × Time-to-Resolution

Every candidate trade gets scored on three axes. The composite score determines position size and whether the trade qualifies for the safe subset.

### 3.1 Edge Score (E) — Scale: 0 to 10

Measures how much the market price diverges from your resolution-informed fair value.

| Score | Meaning |
|-------|---------|
| 0–2   | Negligible. Market is pricing the correct resolution reading. |
| 3–4   | Mild. Market is slightly off, likely due to low attention, not misunderstanding. |
| 5–6   | Moderate. Clear evidence the market is pricing a different resolution interpretation than the technically correct one. |
| 7–8   | Strong. Majority of traders are demonstrably misreading the rules, and the correct reading is unambiguous. |
| 9–10  | Extreme. Near-certain mispricing. The rules clearly say X, the market is pricing Y, and there is platform precedent confirming your reading. |

**How to score:** Compare the market price to what you believe it would be if every participant read the rules carefully. The gap is your edge. Assign the score based on implied probability differential (e.g., market at 70%, your read says 95% → that's ~25 points of implied edge → E = 7–8).

### 3.2 Dispute Probability (D) — Scale: 0 to 10

Measures the likelihood the resolution will be contested, delayed, or overridden.

| Score | Meaning |
|-------|---------|
| 0–2   | Very low. Rule is clear, source is unambiguous, platform has resolved identical markets cleanly before. |
| 3–4   | Low. Minor ambiguity exists but the weight of the reading is heavily on one side. |
| 5–6   | Moderate. Reasonable people could disagree. The platform may need to make a judgment call. |
| 7–8   | High. Multiple valid interpretations. Platform has no precedent. Disputes are likely. |
| 9–10  | Very high. Rule is genuinely broken or contradictory. Resolution will almost certainly be contested or voided. |

**How to score:** Count the number of checklist flags, weight by taxonomy category (F flags count double), and calibrate against your database of past disputes on this platform.

### 3.3 Time-to-Resolution (T) — Scale: 0 to 10

Measures how long your capital will be locked and exposed to resolution uncertainty.

| Score | Meaning |
|-------|---------|
| 0–2   | Fast. Resolves within 48 hours of the event, with minimal delay risk. |
| 3–4   | Short. Resolves within 1–2 weeks. Some potential for minor delays. |
| 5–6   | Medium. 2–8 weeks. Source data may be revised, or platform may take time to adjudicate. |
| 7–8   | Long. 2–6 months. Significant capital lockup. Resolution depends on slow-moving processes. |
| 9–10  | Extended. 6+ months, or no clear resolution timeline. High opportunity cost. |

**How to score:** Estimate the expected number of days to resolution, then add a buffer for the platform's historical resolution speed and the dispute probability.

### 3.4 Composite Score

```
Composite = E - (0.5 × D) - (0.3 × T)
```

**Interpretation:**

| Composite | Action |
|-----------|--------|
| ≥ 6.0    | Strong trade. Full position within safe-subset rules. |
| 4.0–5.9  | Viable trade. Reduced position. Monitor actively. |
| 2.0–3.9  | Marginal. Trade only if portfolio needs the exposure and D ≤ 4. |
| < 2.0    | No trade. Edge doesn't compensate for risk and time cost. |

**Example:**
A market has E = 8 (strong mispricing based on rule misread), D = 3 (minor ambiguity, good precedent), T = 2 (resolves quickly).
Composite = 8 - (0.5 × 3) - (0.3 × 2) = 8 - 1.5 - 0.6 = **5.9** → Viable, near-strong. Trade with moderate size.

---

## 4. Safe-Subset Rules

A trade qualifies for the safe subset — meaning you can size it at full allocation — only if ALL of the following conditions are met.

### 4.1 Mandatory Conditions (all must hold)

1. **Explicit source.** The resolution rule names a specific, verifiable source. Taxonomy Category A flags must be zero.

2. **No platform discretion override.** The rule does not contain language granting the platform unilateral resolution power, OR there is documented precedent (≥3 prior markets) showing the platform defers to the stated source.

3. **Dispute score ≤ 4.** Your D score is 4 or below. At D = 5+, you are making a bet on the dispute process, not on the event.

4. **Time score ≤ 5.** Your T score is 5 or below. Capital locked beyond 8 weeks must earn a significantly higher edge to compensate.

5. **Composite ≥ 4.0.** The trade clears the minimum composite threshold.

6. **Liquidity to exit.** The order book has sufficient depth to allow you to exit at least 50% of your position within 1% of the current price.

7. **No active rule change.** The platform has not amended the market's rules in the last 7 days, and there is no pending proposal to amend them.

### 4.2 Concentration Limits

- No single resolution-edge trade exceeds **5% of total portfolio** at entry.
- Total exposure to resolution-edge trades on a single platform does not exceed **20% of total portfolio**.
- Total exposure to markets with D ≥ 3 does not exceed **15% of total portfolio**.
- No more than **3 active positions** in markets sharing the same underlying ambiguity type (same taxonomy category on the same topic).

### 4.3 Kill Conditions (exit immediately if any trigger)

- The platform announces a rule change or clarification that invalidates your thesis.
- A dispute is formally opened and the platform's initial response suggests your interpretation may not prevail.
- A comparable market on the same platform resolves against your expected interpretation.
- Liquidity drops below the threshold needed to exit 50% of your position within 2% of the current price.
- The resolution source announces a methodology change, retraction, or significant delay.

---

## 5. Monitoring Protocol

### 5.1 Pre-Trade Setup

For every resolution-edge trade entered, create a monitoring record with:

- Market ID and platform
- Entry price, size, and date
- Your resolution thesis (one paragraph: what the rules say, why the market is wrong)
- Taxonomy category of the ambiguity
- E, D, T scores and composite
- Named resolution source and its expected publication date
- Link to the specific rule text (screenshot it — rules can change)
- Calendar reminders: (a) 7 days before expected resolution, (b) day of expected resolution, (c) 7 days after if unresolved

### 5.2 Ongoing Monitoring Cadence

| Check | Frequency | What to look for |
|-------|-----------|-----------------|
| Rule text comparison | Every 48 hours | Has the platform silently edited the resolution criteria? Diff against your screenshot. |
| Source status | Daily once within 7 days of resolution | Has the oracle/source published? Any revisions, delays, or retractions? |
| Dispute tracker | Daily once within 7 days of resolution | Has a dispute been filed? What is the platform's response? |
| Order book depth | Every 24 hours | Can you still exit? Has liquidity deteriorated? |
| Comparable market scan | Weekly | Are similar markets resolving in ways that inform your thesis? |
| Platform announcements | Daily | Blog posts, tweets, Discord messages from the platform about resolution policy. |

### 5.3 Dispute Response Protocol

**If a dispute is filed on your market:**

1. **Within 1 hour:** Read the dispute in full. Classify the challenger's argument. Does it have merit under the stated rules?
2. **If the challenge is weak** (doesn't cite rule text, relies on "common sense" or "intent"): Hold. Monitor platform response. These often fail.
3. **If the challenge cites a genuine ambiguity you scored D ≤ 3:** Reassess D. If you'd now score it D ≥ 5, reduce position by 50% immediately.
4. **If the platform signals it may side with the challenger:** Exit fully. Do not wait for the final ruling. The expected-value math shifts the moment the platform telegraphs a direction.
5. **Log everything.** The dispute outcome — win or lose — feeds your calibration data for future D scoring on this platform.

### 5.4 Post-Resolution Review

After every resolution-edge trade (win or lose):

- **Was your resolution reading correct?** If not, what did you miss?
- **Was your E score calibrated?** Compare the price you traded at to the resolution value.
- **Was your D score calibrated?** Was there a dispute? How long did it take?
- **Was your T score calibrated?** How many days from event to payout?
- **Update your platform precedent database.** Each resolution is a data point for future scoring.
- **Recalibrate the composite formula weights** (0.5 on D, 0.3 on T) quarterly using your realized P&L data. The weights should reflect your actual experience of how disputes and delays erode returns.

---

## Appendix: Quick-Reference Decision Tree

```
START: New market identified with potential resolution-rule edge
  │
  ├─ Run Ambiguity Scanning Checklist (Section 1)
  │    └─ Any flags? ──── No flags ──→ Not a resolution-edge trade. Use standard process.
  │         │
  │        Yes
  │         │
  ├─ Classify flags by Taxonomy (Section 2)
  │    └─ Category F dominant? ──── Yes ──→ STOP. Platform discretion = unhedgeable.
  │         │
  │        No
  │         │
  ├─ Score E, D, T (Section 3)
  │    └─ Composite < 2.0? ──── Yes ──→ NO TRADE.
  │         │
  │        No
  │         │
  ├─ Check Safe-Subset Rules (Section 4)
  │    └─ All conditions met? ──── No ──→ Reduce size or pass.
  │         │
  │        Yes
  │         │
  ├─ Enter trade. Set up monitoring record (Section 5.1).
  │
  └─ Run monitoring cadence until resolution (Section 5.2–5.4).
```

---

*This playbook is a risk-management framework, not legal or financial advice. Calibrate all scores to your own data and platform experience.*
