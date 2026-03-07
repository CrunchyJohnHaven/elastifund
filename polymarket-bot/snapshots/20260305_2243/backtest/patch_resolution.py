#!/usr/bin/env python3
"""Patch improvement_loop.py to add market resolution logic."""
import sys

LOOP_FILE = "/home/botuser/polymarket-trading-bot/scripts/improvement_loop.py"

RESOLUTION_CODE = '''
        # --- STEP 4b: RESOLVE OPEN POSITIONS ---
        try:
            open_positions = list(self.trader.portfolio.open_positions)
            if open_positions:
                import requests as _req
                resolved_count = 0
                for pos in open_positions:
                    cid = pos.market_condition_id
                    if not cid:
                        continue
                    try:
                        resp = _req.get(
                            "https://gamma-api.polymarket.com/markets/" + cid,
                            timeout=10,
                        )
                        if resp.status_code != 200:
                            continue
                        mdata = resp.json()
                        if not mdata.get("closed"):
                            continue
                        outcomes = mdata.get("outcomePrices", [])
                        if isinstance(outcomes, str):
                            import json as _jmod
                            outcomes = _jmod.loads(outcomes)
                        if len(outcomes) >= 2:
                            yes_price = float(outcomes[0])
                            no_price = float(outcomes[1])
                            if yes_price > 0.90:
                                outcome = True
                            elif no_price > 0.90:
                                outcome = False
                            else:
                                continue
                            trade = self.trader.resolve_trade(pos.trade_id, outcome)
                            if trade:
                                resolved_count += 1
                                logger.info("RESOLVED: %s -> %s P&L=$%.2f" % (trade.trade_id, trade.status, trade.pnl))
                                self.telegram.send(
                                    "%s *%s* %s\\nP&L: $%+.2f | Total: $%+.2f" % (
                                        "V" if trade.status == "WIN" else "X",
                                        trade.status,
                                        trade.question[:50],
                                        trade.pnl,
                                        self.trader.portfolio.realized_pnl,
                                    )
                                )
                        time.sleep(0.5)
                    except Exception as e2:
                        logger.debug("Resolution check failed for %s: %s" % (cid, e2))
                if resolved_count > 0:
                    metrics["resolved_trades"] = resolved_count
                    logger.info("Resolved %d trades this cycle" % resolved_count)
        except Exception as e:
            logger.error("Resolution step failed: %s" % e)
            metrics["errors"].append("resolve: %s" % e)

'''

def patch():
    with open(LOOP_FILE) as f:
        content = f.read()

    marker = "        # --- STEP 5: PAPER TRADE ---"
    if "STEP 4b" in content:
        print("Already patched")
        return

    if marker not in content:
        print("ERROR: marker not found in file")
        sys.exit(1)

    content = content.replace(marker, RESOLUTION_CODE + marker)

    with open(LOOP_FILE, "w") as f:
        f.write(content)

    print("Resolution logic added successfully")

if __name__ == "__main__":
    patch()
