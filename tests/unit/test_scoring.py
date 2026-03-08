from __future__ import annotations

from tictoc_factory.models import ContentCandidate
from tictoc_factory.scoring import ViralScoreCalculator


def test_viral_scoring_prefers_high_signal_story(reddit_posts: list[dict[str, object]]) -> None:
    calculator = ViralScoreCalculator()
    hot = ContentCandidate.model_validate(reddit_posts[0])
    cold = ContentCandidate.model_validate(reddit_posts[1])

    hot_score = calculator.score_candidate(hot)
    cold_score = calculator.score_candidate(cold)

    assert hot_score.total > cold_score.total
    assert hot_score.reasons[0]
    assert hot_score.normalized > 0.6


def test_viral_scoring_penalizes_short_flat_content() -> None:
    calculator = ViralScoreCalculator()
    candidate = ContentCandidate(
        id="flat",
        subreddit="confessions",
        title="I like toast",
        body="fine",
        score=10,
        num_comments=0,
        created_utc=1730985600,
    )

    result = calculator.score_candidate(candidate)

    assert result.normalized < 0.25
