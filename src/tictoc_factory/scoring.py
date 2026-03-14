from __future__ import annotations

import math

from .models import ContentCandidate, ViralScoreResult

EMOTIONAL_MARKERS = {
    "shocking",
    "whisper",
    "caught",
    "secret",
    "confession",
    "exploded",
    "fire",
    "weirdest",
    "nobody",
    "never",
}


class ViralScoreCalculator:
    def score_candidate(self, candidate: ContentCandidate) -> ViralScoreResult:
        title_text = f"{candidate.title} {candidate.body}".lower()
        marker_hits = sum(1 for token in EMOTIONAL_MARKERS if token in title_text)
        engagement = math.log1p(max(candidate.score, 0)) / 4
        comments = math.log1p(max(candidate.num_comments, 0)) / 3
        length_words = len(candidate.body.split())
        if 160 <= length_words <= 320:
            length_fit = 1.8
        elif 120 <= length_words <= 420:
            length_fit = 1.1
        else:
            length_fit = 0.4
        marker_boost = marker_hits * 0.8
        total = engagement + comments + length_fit + marker_boost
        normalized = min(total / 8.0, 1.0)
        reasons = [
            f"engagement={engagement:.2f}",
            f"comments={comments:.2f}",
            f"markers={marker_hits}",
            f"length_fit={length_fit:.2f}",
        ]
        return ViralScoreResult(
            total=total,
            normalized=normalized,
            reasons=reasons,
            metrics={
                "engagement": engagement,
                "comments": comments,
                "marker_boost": marker_boost,
                "length_fit": length_fit,
            },
        )
