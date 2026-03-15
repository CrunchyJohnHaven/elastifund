"""Shared best-effort fast JSON helpers for market-data hot paths."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency
    import msgspec
except Exception:  # pragma: no cover - optional dependency
    msgspec = None


_DECODER = msgspec.json.Decoder() if msgspec is not None else None


def loads(raw: str | bytes | bytearray | memoryview) -> Any:
    if _DECODER is not None:
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        elif isinstance(raw, memoryview):
            raw = raw.tobytes()
        try:
            return _DECODER.decode(raw)
        except Exception as exc:
            raise ValueError(str(exc)) from exc

    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    return json.loads(raw)


def dumps(payload: Any, *, indent: int | None = None, sort_keys: bool = False) -> str:
    if msgspec is not None:
        try:
            encoded = msgspec.json.encode(payload)
            if indent is None and not sort_keys:
                return encoded.decode("utf-8")
        except Exception:
            pass
    return json.dumps(payload, indent=indent, sort_keys=sort_keys)


def load_path(path: str | Path, *, encoding: str = "utf-8") -> Any:
    text = Path(path).read_text(encoding=encoding)
    return loads(text)


def dump_path_atomic(
    path: str | Path,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
    trailing_newline: bool = True,
    encoding: str = "utf-8",
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = dumps(payload, indent=indent, sort_keys=sort_keys)
    if trailing_newline:
        rendered += "\n"

    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(rendered)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def fast_path_enabled() -> bool:
    return _DECODER is not None
