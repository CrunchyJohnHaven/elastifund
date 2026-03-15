# Tweet 02 — Quarter-Kelly
**Pillar:** Position Sizing Math
**Priority:** High (concrete result, screenshottable formula)

---

Kelly criterion for prediction markets:

f* = (p_true - p_market) / ((1 - p_market) / p_market)

Full Kelly is theoretically optimal. In practice it'll blow you up.

Quarter-Kelly backtest across 532 markets:
- Flat $2 sizing → $330.60 (341% return)
- 0.25× Kelly → $1,353.18 (1,704% return)

309% outperformance. Same edge. Different sizing. The formula is trivial. The discipline to use it isn't.

---

**Notes:** Thread candidate — could expand into full Kelly vs fractional Kelly breakdown with bankroll scaling tiers.
