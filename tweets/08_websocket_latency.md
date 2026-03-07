# Tweet 08 — WebSocket vs REST Latency
**Pillar:** Infrastructure & Latency
**Priority:** Medium (practical, saves builders time)

---

If you're polling Polymarket REST endpoints every few minutes, you're leaving 900ms on the table per cycle.

Our observe-to-match breakdown (Dublin → London CLOB):
- Observe: ~100ms (WebSocket) vs ~1000ms (REST poll)
- Compute: <1ms
- Submit: 15-35ms
- Match: 10-50ms

Total floor: 70-150ms on WebSocket.

Polymarket's CLOB is in eu-west-2 (London), not the US. Your VPS placement matters less than your data feed architecture.

You don't need colocation. You need to stop polling.

---

**Notes:** Practical infrastructure advice. The "CLOB is in London" fact surprises most US-based builders.
