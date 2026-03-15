import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Compatibility shim: direct `pytest tests/...` invocations in editor tools
# should resolve root-package imports the same way as repo-root runs.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
