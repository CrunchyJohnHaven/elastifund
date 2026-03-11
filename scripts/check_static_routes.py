#!/usr/bin/env python3
"""Validate core static route files and targeted internal links."""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

TARGET_ROUTE_FILES = {
    "/": ROOT / "index.html",
    "/develop/": ROOT / "develop" / "index.html",
    "/elastic/": ROOT / "elastic" / "index.html",
    "/live/": ROOT / "live" / "index.html",
    "/leaderboards/": ROOT / "leaderboards" / "index.html",
    "/leaderboards/trading/": ROOT / "leaderboards" / "trading" / "index.html",
    "/leaderboards/worker/": ROOT / "leaderboards" / "worker" / "index.html",
    "/manage/": ROOT / "manage" / "index.html",
    "/roadmap/": ROOT / "roadmap" / "index.html",
}

SKIP_SCHEMES = {"http", "https", "mailto", "tel", "javascript"}
ID_RE = re.compile(r'id="([^"]+)"')


class HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)
                return


def normalize_route(path: str) -> str:
    if not path:
        return "/"
    if path == "/":
        return "/"
    return path if path.endswith("/") else f"{path}/"


def collect_hrefs(html_path: Path) -> list[str]:
    parser = HrefParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    return parser.hrefs


def collect_ids(html_path: Path) -> set[str]:
    text = html_path.read_text(encoding="utf-8")
    return set(ID_RE.findall(text))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_static_routes() -> list[str]:
    issues: list[str] = []
    inbound_counts = {route: 0 for route in TARGET_ROUTE_FILES if route != "/"}

    for route, file_path in TARGET_ROUTE_FILES.items():
        if not file_path.exists():
            issues.append(f"{route}: missing route file ({display_path(file_path)})")
            continue

    for source_route, source_file in TARGET_ROUTE_FILES.items():
        if not source_file.exists():
            continue
        source_hrefs = collect_hrefs(source_file)

        for href in source_hrefs:
            parsed = urlparse(href)
            if parsed.scheme in SKIP_SCHEMES:
                continue
            if href.startswith("#"):
                continue
            if not href.startswith("/"):
                continue

            target_path = parsed.path or "/"
            target_route = normalize_route(target_path)
            if target_route not in TARGET_ROUTE_FILES:
                continue

            target_file = TARGET_ROUTE_FILES[target_route]
            if not target_file.exists():
                issues.append(
                    f"{source_route}: link {href} points to missing route file "
                    f"({display_path(target_file)})"
                )
                continue

            if target_route != "/" and source_route != target_route:
                inbound_counts[target_route] += 1

            fragment = parsed.fragment
            if fragment:
                target_ids = collect_ids(target_file)
                if fragment not in target_ids:
                    issues.append(
                        f"{source_route}: link {href} points to missing id '#{fragment}' "
                        f"in {display_path(target_file)}"
                    )

    for route, count in inbound_counts.items():
        if count == 0:
            issues.append(f"{route}: no inbound links from other targeted routes")

    return issues


def main() -> int:
    issues = check_static_routes()
    if issues:
        print("Static route check failed:")
        for issue in issues:
            print(f" - {issue}")
        return 1
    print("Static route check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
