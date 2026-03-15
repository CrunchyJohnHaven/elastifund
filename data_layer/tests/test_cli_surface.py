from __future__ import annotations

import pytest

from data_layer import cli


def test_cli_help_lists_canonical_flywheel_commands(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    for command in (
        "flywheel-cycle",
        "flywheel-scorecard",
        "flywheel-bridge",
        "flywheel-kibana-pack",
        "flywheel-naming-check",
    ):
        assert command in out


def test_cli_help_description_is_control_plane_oriented(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    out = capsys.readouterr().out
    assert "Control-plane persistence CLI" in out
