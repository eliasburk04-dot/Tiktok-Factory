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


def test_viral_scoring_prefers_story_length_close_to_target_window() -> None:
    calculator = ViralScoreCalculator()
    short_candidate = ContentCandidate(
        id="short",
        subreddit="confessions",
        title="Something awkward happened at dinner",
        body=" ".join(["short"] * 25),
        score=2500,
        num_comments=300,
        created_utc=1730985600,
    )
    target_candidate = ContentCandidate(
        id="target",
        subreddit="confessions",
        title="Something awkward happened at dinner",
        body=" ".join(["target"] * 220),
        score=2500,
        num_comments=300,
        created_utc=1730985600,
    )

    short_result = calculator.score_candidate(short_candidate)
    target_result = calculator.score_candidate(target_candidate)

    assert target_result.metrics["length_fit"] > short_result.metrics["length_fit"]
    assert target_result.total > short_result.total
