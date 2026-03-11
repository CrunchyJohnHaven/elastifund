from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_FIXTURES = REPO_ROOT / "tests" / "fixtures"
NONTRADING_FIXTURES = REPO_ROOT / "nontrading" / "tests" / "fixtures"
FIXTURE_REF_PATTERN = re.compile(
    r"""["'](?P<path>(?:tests/fixtures|nontrading/tests/fixtures)/[^"']+)["']"""
)


def _relative_fixture_set(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _python_test_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("test_*.py") if path.is_file())


def _fixture_refs(path: Path) -> set[str]:
    matches = FIXTURE_REF_PATTERN.findall(path.read_text(encoding="utf-8"))
    return set(matches)


def test_fixture_name_space_is_unambiguous_between_root_and_nontrading_lanes() -> None:
    root_rel = _relative_fixture_set(ROOT_FIXTURES)
    nontrading_rel = _relative_fixture_set(NONTRADING_FIXTURES)
    overlap = sorted(root_rel & nontrading_rel)
    assert not overlap, (
        "Fixture names overlap across ownership lanes; move or rename to keep one owner "
        f"per relative fixture path: {overlap}"
    )


def test_fixture_path_references_resolve_to_existing_owned_lane() -> None:
    candidate_files = _python_test_files(REPO_ROOT / "tests") + _python_test_files(
        REPO_ROOT / "nontrading" / "tests"
    )
    missing: list[str] = []

    for file_path in candidate_files:
        for fixture_ref in _fixture_refs(file_path):
            abs_ref = REPO_ROOT / fixture_ref
            if not abs_ref.exists():
                missing.append(f"{file_path.relative_to(REPO_ROOT).as_posix()} -> {fixture_ref}")

    assert not missing, (
        "Fixture references must point to existing files in one ownership lane: "
        f"{missing}"
    )


def test_nontrading_lane_filename_collisions_use_contract_suffix_in_root_lane() -> None:
    root_nontrading = REPO_ROOT / "tests" / "nontrading"
    package_nontrading = REPO_ROOT / "nontrading" / "tests"

    root_names = {path.name for path in root_nontrading.glob("test_*.py")}
    package_names = {path.name for path in package_nontrading.glob("test_*.py")}
    collisions = sorted(root_names & package_names)

    assert not collisions, (
        "Root nontrading tests must not share exact filenames with nontrading/tests. "
        "Use *_contract.py suffix in tests/nontrading for cross-surface contracts: "
        f"{collisions}"
    )
