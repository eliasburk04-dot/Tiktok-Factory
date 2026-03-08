from __future__ import annotations

from typing import Protocol

from ..models import ContentCandidate


class DiscoveryProvider(Protocol):
    def fetch_candidates(self, subreddits: list[str], limit_per_subreddit: int = 5) -> list[ContentCandidate]:
        """Return discoverable source candidates."""
        ...
