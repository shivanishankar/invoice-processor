"""Structured, coloured console logging using Rich."""
from __future__ import annotations

from datetime import datetime
from rich.console import Console
from rich.text import Text

_console = Console(highlight=False)

_STAGE_COLORS = {
    "INGEST": "cyan",
    "VALIDATE": "yellow",
    "APPROVE": "magenta",
    "PAYMENT": "green",
    "REJECT": "red",
    "BATCH": "blue",
}


class _Logger:
    def _prefix(self, stage: str) -> Text:
        color = _STAGE_COLORS.get(stage.upper(), "white")
        ts = datetime.now().strftime("%H:%M:%S")
        t = Text()
        t.append(f"[{ts}] ", style="dim")
        t.append(f"[{stage:7s}] ", style=f"bold {color}")
        return t

    def stage(self, stage: str, msg: str):
        t = self._prefix(stage)
        t.append("▶ " + msg, style="bold white")
        _console.print(t)

    def info(self, stage: str, msg: str):
        t = self._prefix(stage)
        t.append(msg, style="white")
        _console.print(t)

    def success(self, stage: str, msg: str):
        t = self._prefix(stage)
        t.append("✓ " + msg, style="green")
        _console.print(t)

    def warning(self, stage: str, msg: str):
        t = self._prefix(stage)
        t.append("⚠ " + msg, style="yellow")
        _console.print(t)

    def error(self, stage: str, msg: str):
        t = self._prefix(stage)
        t.append("✗ " + msg, style="red")
        _console.print(t)

    def separator(self):
        _console.print("─" * 70, style="dim")


logger = _Logger()
