from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tictoc_factory.config import load_settings
from tictoc_factory.models import ContentCandidate
from tictoc_factory.pipeline.orchestrator import FactoryPipeline


def test_pipeline_skips_reddit_candidates_that_cannot_hit_target_duration(tmp_path: Path) -> None:
    for relative in [
        "configs",
        "data/input/gameplay",
        "data/input/gameplay_longform",
        "data/input/longform/podcasts_streams",
        "data/work",
        "data/output/videos",
        "data/output/audio",
        "data/output/subtitles",
        "data/output/scripts",
        "data/analytics",
        "data/queue/jobs",
        "logs",
    ]:
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)

    (tmp_path / "configs" / "factory.local.yaml").write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits: [nosleep]
providers:
  llm_provider: openai
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
tts:
  provider: tone
story_pacing:
  target_duration_seconds_min: 60
  target_duration_seconds_max: 80
  estimated_characters_per_minute: 240
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [30]
content_policy:
  max_posts_per_day: 4
  min_source_score: 100
"""
    )
    (tmp_path / "configs" / "accounts.local.yaml").write_text(
        """
accounts:
  - name: local-test
    posting_windows: ["09:00-11:00"]
"""
    )

    settings = load_settings(
        tmp_path / "configs" / "factory.local.yaml",
        tmp_path / "configs" / "accounts.local.yaml",
        project_root=tmp_path,
    )
    pipeline = FactoryPipeline(settings)
    pipeline._discover_reddit_candidates = lambda: [  # type: ignore[method-assign]
        ContentCandidate(
            id="too-short",
            subreddit="nosleep",
            title="Too short",
            body="Just a few words.",
            score=5000,
            num_comments=400,
            created_utc=1730985600,
        ),
        ContentCandidate(
            id="long-enough",
            subreddit="nosleep",
            title="Long enough",
            body=" ".join(["This sentence gives the story enough texture and detail."] * 12),
            score=5000,
            num_comments=400,
            created_utc=1730985600,
        ),
    ]

    created = pipeline._discover_jobs(datetime(2026, 3, 7, 9, 0, tzinfo=UTC))

    jobs = pipeline.queue.list_jobs()
    assert created == 1
    assert len(jobs) == 1
    assert jobs[0].job_id.startswith("reddit-long-enough-")


def test_pipeline_skips_reddit_batch_when_no_candidate_can_hit_target_duration(tmp_path: Path) -> None:
    for relative in [
        "configs",
        "data/input/gameplay",
        "data/input/gameplay_longform",
        "data/input/longform/podcasts_streams",
        "data/work",
        "data/output/videos",
        "data/output/audio",
        "data/output/subtitles",
        "data/output/scripts",
        "data/analytics",
        "data/queue/jobs",
        "logs",
    ]:
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)

    (tmp_path / "configs" / "factory.local.yaml").write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits: [nosleep]
providers:
  llm_provider: openai
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
tts:
  provider: tone
story_pacing:
  target_duration_seconds_min: 60
  target_duration_seconds_max: 80
  estimated_characters_per_minute: 240
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [30]
content_policy:
  max_posts_per_day: 4
  min_source_score: 100
"""
    )
    (tmp_path / "configs" / "accounts.local.yaml").write_text(
        """
accounts:
  - name: local-test
    posting_windows: ["09:00-11:00"]
"""
    )

    settings = load_settings(
        tmp_path / "configs" / "factory.local.yaml",
        tmp_path / "configs" / "accounts.local.yaml",
        project_root=tmp_path,
    )
    pipeline = FactoryPipeline(settings)
    pipeline._discover_reddit_candidates = lambda: [  # type: ignore[method-assign]
        ContentCandidate(
            id="too-short-one",
            subreddit="nosleep",
            title="Too short one",
            body="Just a few words.",
            score=5000,
            num_comments=400,
            created_utc=1730985600,
        ),
        ContentCandidate(
            id="too-short-two",
            subreddit="nosleep",
            title="Too short two",
            body="Still nowhere near a minute.",
            score=5000,
            num_comments=400,
            created_utc=1730985600,
        ),
    ]

    created = pipeline._discover_jobs(datetime(2026, 3, 7, 9, 0, tzinfo=UTC))

    assert created == 0
    assert pipeline.queue.list_jobs() == []
