"""Static naming guardrails for flywheel cycle-packet surfaces."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

TARGET_FILES = (
    "flywheel/bridge.py",
    "flywheel/automation.py",
    "flywheel/runner.py",
)

_ALLOWED_PAYLOAD_FUNCTIONS = {
    "build_payload_from_bot_db",
    "write_payload",
    "build_payload_from_config",
    "load_payload",
    "run_cycle",
    "run_from_config",
}


class _PayloadNameVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.function_stack: list[str] = []
        self.violations: list[dict[str, Any]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_arg(self, node: ast.arg) -> Any:
        if node.arg == "payload" and not self._in_allowed_function():
            self.violations.append(
                {
                    "line": node.lineno,
                    "symbol": "payload",
                    "context": self._context_label(),
                    "kind": "argument",
                }
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id == "payload" and not self._in_allowed_function():
            self.violations.append(
                {
                    "line": node.lineno,
                    "symbol": "payload",
                    "context": self._context_label(),
                    "kind": "name",
                }
            )
        self.generic_visit(node)

    def _in_allowed_function(self) -> bool:
        if not self.function_stack:
            return False
        return self.function_stack[-1] in _ALLOWED_PAYLOAD_FUNCTIONS

    def _context_label(self) -> str:
        if not self.function_stack:
            return "<module>"
        return self.function_stack[-1]


def run_cycle_packet_naming_check(repo_root: Path | None = None) -> dict[str, Any]:
    """Return naming-check results for cycle-packet code paths.

    Rule: outside compatibility alias functions, avoid the ambiguous symbol name
    `payload` in flywheel cycle-packet modules.
    """

    root = (repo_root or Path.cwd()).resolve()
    violations: list[dict[str, Any]] = []
    checked_files: list[str] = []

    for rel_path in TARGET_FILES:
        path = root / rel_path
        if not path.exists():
            continue
        checked_files.append(str(path))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _PayloadNameVisitor()
        visitor.visit(tree)
        for issue in visitor.violations:
            violations.append({"file": str(path), **issue})

    return {
        "ok": not violations,
        "checked_files": checked_files,
        "violations": violations,
    }
