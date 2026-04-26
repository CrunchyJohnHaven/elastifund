import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Disable time-sensitive production gates so unit tests pass regardless of the
# local clock or current market regime. Production deployments keep these at
# "true" (the default).
os.environ.setdefault("JJ_TOD_KILL_ENABLED", "false")
os.environ.setdefault("JJ_BTC_REPLAY_GATE_ENABLED", "false")
os.environ.setdefault("JJ_BTC5_DIRECTIONAL_LIVE_FROZEN", "false")
