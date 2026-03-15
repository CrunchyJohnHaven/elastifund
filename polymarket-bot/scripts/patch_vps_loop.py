#!/usr/bin/env python3
"""Patch the VPS improvement_loop.py to integrate Bayesian and LMSR modules."""

LOOP_FILE = "/home/botuser/polymarket-trading-bot/scripts/improvement_loop.py"

with open(LOOP_FILE, "r") as f:
    content = f.read()

patched = False

# 1. Add imports after existing imports
if "BayesianSignalProcessor" not in content:
    old_imports = "from src.paper_trader import PaperTrader"
    new_imports = (
        "from src.paper_trader import PaperTrader\n"
        "from src.bayesian_signal import (\n"
        "    BayesianSignalProcessor,\n"
        "    evidence_from_claude,\n"
        "    evidence_from_price_move,\n"
        ")\n"
        "from src.lmsr import detect_inefficiency"
    )
    content = content.replace(old_imports, new_imports)
    patched = True
    print("  + Added Bayesian/LMSR imports")

# 2. Add Bayesian processor init in ImprovementLoop.__init__
if "self.bayesian" not in content:
    old_init = "self.metrics_history = self._load_metrics()"
    new_init = (
        "self.metrics_history = self._load_metrics()\n"
        "        # Bayesian signal processor (QR-PM-2026-0041)\n"
        "        self.bayesian = BayesianSignalProcessor(\n"
        "            evidence_decay_hours=24.0,\n"
        "            max_log_odds=5.0,\n"
        "        )"
    )
    content = content.replace(old_init, new_init)
    patched = True
    print("  + Added BayesianSignalProcessor init")

# 3. Add Bayesian update after signal logging
#    Insert right after the signal log line
if "evidence_from_claude(s.estimated_prob" not in content:
    old_line = '                        f"{s.confidence} | {s.question[:50]}"'
    insert_after = old_line + "\n                    )"
    bayesian_block = (
        insert_after + "\n"
        "                    # Bayesian belief updating with Claude evidence\n"
        "                    try:\n"
        "                        if hasattr(s, 'estimated_prob') and 0.01 < s.estimated_prob < 0.99:\n"
        "                            conf_val = 0.8 if s.confidence == 'high' else (0.5 if s.confidence == 'medium' else 0.3)\n"
        "                            ev = evidence_from_claude(s.estimated_prob, conf_val)\n"
        "                            mid = getattr(s, 'condition_id', '') or s.question[:30]\n"
        "                            self.bayesian.update(mid, ev)\n"
        "                    except Exception:\n"
        "                        pass"
    )
    content = content.replace(insert_after, bayesian_block)
    patched = True
    print("  + Added Bayesian evidence update in signal loop")

if patched:
    with open(LOOP_FILE, "w") as f:
        f.write(content)
    print("Patch applied successfully")
else:
    print("Already patched — no changes needed")
