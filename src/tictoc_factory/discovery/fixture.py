from __future__ import annotations

import json
from pathlib import Path

from ..models import ContentCandidate


class FixtureDiscoveryProvider:
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def fetch_candidates(self, subreddits: list[str], limit_per_subreddit: int = 5) -> list[ContentCandidate]:
        payload = json.loads(self.fixture_path.read_text())
        candidates = [ContentCandidate.model_validate(item) for item in payload]
        allowed = {item.lower() for item in subreddits}
        filtered = [item for item in candidates if item.subreddit.lower() in allowed]
        return filtered[: max(limit_per_subreddit, len(filtered))]
