from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

BOT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BOT_ROOT.parent
ROOT_SRC = PROJECT_ROOT / "src"
POLYMARKET_SRC = PROJECT_ROOT / "polymarket-bot" / "src"
_UNSET = object()
_RUNTIME_EXPORTS = {
    "MarketScanner": ("scanner", "MarketScanner"),
    "ClaudeAnalyzer": ("claude_analyzer", "ClaudeAnalyzer"),
}
_runtime_export_cache: dict[str, Any] = {}
_telegram_notifier_cls: Any = _UNSET


def _load_root_src_package() -> ModuleType:
    module = sys.modules.get("src")
    if module is not None:
        return module

    init_py = ROOT_SRC / "__init__.py"
    if not init_py.exists():
        raise ImportError(f"Expected root src package at {init_py}")

    spec = importlib.util.spec_from_file_location(
        "src",
        init_py,
        submodule_search_locations=[str(ROOT_SRC)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load package spec for {init_py}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["src"] = module
    spec.loader.exec_module(module)
    return module


def _ensure_polymarket_src_path() -> None:
    src_pkg = _load_root_src_package()
    pkg_paths = getattr(src_pkg, "__path__", None)
    if pkg_paths is None:
        raise ImportError("Root src module is not a package")

    poly_path = str(POLYMARKET_SRC)
    if poly_path not in pkg_paths:
        pkg_paths.append(poly_path)
        importlib.invalidate_caches()


def import_polymarket_module(module_name: str) -> ModuleType:
    if not POLYMARKET_SRC.exists():
        raise ImportError(f"Expected polymarket runtime at {POLYMARKET_SRC}")

    _ensure_polymarket_src_path()
    return importlib.import_module(f"src.{module_name}")


def _load_runtime_export(name: str) -> Any:
    cached = _runtime_export_cache.get(name, _UNSET)
    if cached is not _UNSET:
        return cached

    module_name, attr_name = _RUNTIME_EXPORTS[name]
    value = getattr(import_polymarket_module(module_name), attr_name)
    _runtime_export_cache[name] = value
    return value


def _load_telegram_notifier_class() -> Any:
    global _telegram_notifier_cls
    if _telegram_notifier_cls is not _UNSET:
        return _telegram_notifier_cls

    try:
        telegram_module = import_polymarket_module("telegram")
    except ImportError:
        _telegram_notifier_cls = None
    else:
        _telegram_notifier_cls = getattr(telegram_module, "TelegramNotifier", None)
    return _telegram_notifier_cls


class TelegramBot:
    def __init__(self, *args, **kwargs):
        notifier_cls = _load_telegram_notifier_class()
        if notifier_cls is None:
            raise ImportError("TelegramNotifier is unavailable")
        self._notifier = notifier_cls(*args, **kwargs)

    @property
    def enabled(self) -> bool:
        if hasattr(self._notifier, "enabled"):
            return bool(self._notifier.enabled)
        return bool(getattr(self._notifier, "is_configured", False))

    def send(self, text: str, parse_mode: str = "HTML"):
        send_message = getattr(self._notifier, "send_message", None)
        if send_message is None:
            raise AttributeError("Telegram notifier does not expose send_message")

        coro = send_message(text, parse_mode=parse_mode)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("TelegramBot.send cannot be used inside a running event loop")


def __getattr__(name: str) -> Any:
    if name in _RUNTIME_EXPORTS:
        return _load_runtime_export(name)
    if name == "TelegramNotifier":
        return _load_telegram_notifier_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ClaudeAnalyzer",
    "MarketScanner",
    "TelegramBot",
    "TelegramNotifier",
    "import_polymarket_module",
]
