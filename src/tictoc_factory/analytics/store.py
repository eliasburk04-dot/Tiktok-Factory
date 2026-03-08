from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..utils.files import append_jsonl, atomic_write_json, load_json


class AnalyticsStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.jsonl"
        self.hook_stats_path = self.root / "hook_stats.json"

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        append_jsonl(
            self.events_path,
            {
                "event_type": event_type,
                "recorded_at": datetime.now(UTC).isoformat(),
                **payload,
            },
        )

    def recent_template_ids(self, limit: int = 5) -> list[str]:
        stats = load_json(self.hook_stats_path, {"history": []})
        history = stats.get("history", [])
        return [item["template_id"] for item in history[-limit:]]

    def register_template_use(self, template_id: str, score: float | None = None) -> None:
        stats = load_json(self.hook_stats_path, {"history": [], "totals": {}})
        totals = stats.setdefault("totals", {})
        totals.setdefault(template_id, {"uses": 0, "score_total": 0.0})
        totals[template_id]["uses"] += 1
        if score is not None:
            totals[template_id]["score_total"] += score
        stats.setdefault("history", []).append({"template_id": template_id, "score": score})
        stats["history"] = stats["history"][-50:]
        atomic_write_json(self.hook_stats_path, stats)
