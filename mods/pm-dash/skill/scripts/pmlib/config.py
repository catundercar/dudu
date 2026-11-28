"""Personal settings: config.json in the ledger home, and tr() for built-in text in the configured language. Layer 0.

Config reads the file on every call (a person edits it while sessions run); nothing is cached.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import context


class Config:
    """Un-cached reader for `config.json` and configured UI/ledger language (`en` or `zh`)."""

    def __init__(
        self,
        source: Path | Any | Callable[[], Path],
        *,
        reader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._source = source
        self._reader = reader

    def path(self) -> Path:
        """Return the resolved `config.json` path without touching the disk."""
        src = self._source() if callable(self._source) else self._source
        if isinstance(src, Path):
            return src
        cfg = getattr(src, "config", None)
        if cfg is not None and not callable(cfg):
            return Path(cfg)
        return Path(src)

    def read(self) -> dict[str, Any]:
        """Read `config.json` fresh from disk, returning `{}` if missing or invalid."""
        if self._reader is not None:
            data = self._reader()
            return data if isinstance(data, dict) else {}
        try:
            data = json.loads(self.path().read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.read().get(key, default)

    def experimental(self, name: str) -> bool:
        """An opt-in feature that is built and tested but not offered yet: `{"experimental": {name: true}}`."""
        flags = self.read().get("experimental")
        return isinstance(flags, dict) and flags.get(name) is True

    def lang(self) -> str:
        return "zh" if self.read().get("lang") == "zh" else "en"

    def tr(self, en: str, zh: str) -> str:
        """Built-in text in the configured language: English unless config.json says {"lang": "zh"}."""
        return zh if self.lang() == "zh" else en


def config() -> dict[str, Any]:
    """Personal settings: config.json in the ledger home, for example
    {"worker": {"kind": "codex", "model": "...", "effort": "high"}, "pm": {"kind": "claude"}}."""
    return Config(context.default_home() / "config.json").read()


def tr(en: str, zh: str) -> str:
    """Built-in text in the configured language: English unless config.json says {"lang": "zh"}."""
    return zh if config().get("lang") == "zh" else en
