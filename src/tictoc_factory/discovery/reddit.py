from __future__ import annotations

from typing import Any

import requests

from ..models import ContentCandidate


class RedditDiscoveryProvider:
    def __init__(self, user_agent: str = "tictoc-factory/0.1") -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_candidates(self, subreddits: list[str], limit_per_subreddit: int = 25) -> list[ContentCandidate]:
        candidates: list[ContentCandidate] = []
        for subreddit in subreddits:
            response = self.session.get(
                f"https://www.reddit.com/r/{subreddit}/top.json",
                params={"t": "day", "limit": limit_per_subreddit},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            for child in payload.get("data", {}).get("children", []):
                data: dict[str, Any] = child.get("data", {})
                body = data.get("selftext") or data.get("title", "")
                candidates.append(
                    ContentCandidate(
                        id=str(data["id"]),
                        subreddit=subreddit,
                        title=str(data.get("title", "")),
                        body=str(body),
                        score=int(data.get("score", 0)),
                        num_comments=int(data.get("num_comments", 0)),
                        created_utc=int(data.get("created_utc", 0)),
                        source_url=f"https://reddit.com{data.get('permalink', '')}",
                    )
                )
        return candidates
