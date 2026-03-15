from pathlib import Path

from scripts import check_static_routes


def test_static_route_files_exist() -> None:
    issues = check_static_routes.check_static_routes()
    missing = [issue for issue in issues if "missing route file" in issue]
    assert missing == []


def test_targeted_routes_have_inbound_links() -> None:
    issues = check_static_routes.check_static_routes()
    no_inbound = [issue for issue in issues if "no inbound links" in issue]
    assert no_inbound == []


def test_fragment_validation_detects_broken_anchor(tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    target = tmp_path / "target.html"
    source.write_text('<a href="/target/#missing">Broken</a>', encoding="utf-8")
    target.write_text('<div id="ok"></div>', encoding="utf-8")

    original = dict(check_static_routes.TARGET_ROUTE_FILES)
    try:
        check_static_routes.TARGET_ROUTE_FILES.clear()
        check_static_routes.TARGET_ROUTE_FILES.update(
            {
                "/": source,
                "/target/": target,
            }
        )
        issues = check_static_routes.check_static_routes()
    finally:
        check_static_routes.TARGET_ROUTE_FILES.clear()
        check_static_routes.TARGET_ROUTE_FILES.update(original)

    assert any("missing id '#missing'" in issue for issue in issues)
