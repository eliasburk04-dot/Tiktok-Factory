from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .files import append_jsonl


class StructuredLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, event: str, **payload: Any) -> None:
        append_jsonl(
            self.log_path,
            {
                "level": "info",
                "event": event,
                "timestamp": datetime.now(UTC).isoformat(),
                **payload,
            },
        )

    def error(self, event: str, **payload: Any) -> None:
        append_jsonl(
            self.log_path,
            {
                "level": "error",
                "event": event,
                "timestamp": datetime.now(UTC).isoformat(),
                **payload,
            },
        )
