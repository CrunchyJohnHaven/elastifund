#!/usr/bin/env python3
"""Check public website copy against approved messaging rules."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]

FILES_TO_SCAN = [
    ROOT / "index.html",
    ROOT / "elastic" / "index.html",
    ROOT / "develop" / "index.html",
    ROOT / "leaderboards" / "trading" / "index.html",
    ROOT / "leaderboards" / "worker" / "index.html",
    ROOT / "manage" / "index.html",
    ROOT / "diary" / "index.html",
    ROOT / "roadmap" / "index.html",
    ROOT / "docs" / "index.html",
]

FORBIDDEN_PHRASES = [
    "self-modifying binary",
    "remove the human from the loop",
    "agent swarm that makes money",
]

REQUIRED_SUBSTRINGS = {
    ROOT / "index.html": [
        "A self-improving agentic operating system for real economic work.",
        "paper mode by default",
        "JJ-N",
    ],
    ROOT / "elastic" / "index.html": [
        "Open-source agents need a system memory. Elastic is the Search AI platform that makes them reliable.",
    ],
}


def main() -> int:
    violations = []

    for path in FILES_TO_SCAN:
        if not path.exists():
            violations.append(f"missing file: {path.relative_to(ROOT)}")
            continue

        text = path.read_text(encoding="utf-8")
        lowered = text.lower()

        for phrase in FORBIDDEN_PHRASES:
            if phrase in lowered:
                violations.append(
                    f"forbidden phrase {phrase!r} found in {path.relative_to(ROOT)}"
                )

        for required in REQUIRED_SUBSTRINGS.get(path, []):
            if required not in text:
                violations.append(
                    f"required copy {required!r} missing in {path.relative_to(ROOT)}"
                )

    if violations:
        print("website copy check failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("website copy check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
