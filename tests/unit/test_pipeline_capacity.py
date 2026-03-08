from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tictoc_factory.config import load_settings
from tictoc_factory.models import QueueJob
from tictoc_factory.pipeline.orchestrator import FactoryPipeline


def test_pipeline_limits_daily_processing_capacity(tmp_path: Path) -> None:
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
mode: hybrid
default_subreddits: [nosleep]
providers:
  llm_provider: openai
  tts_provider: espeak
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [25, 35, 45]
content_policy:
  max_posts_per_day: 3
  min_source_score: 100
"""
    )
    (tmp_path / "configs" / "accounts.local.yaml").write_text(
        """
accounts:
  - name: local-test
    enabled: true
    uploader: local_archive
    posting_windows:
      - "16:50-17:10"
      - "18:20-18:40"
      - "19:50-20:10"
    timezone: Europe/Berlin
    template_tags: ["story", "clip"]
    min_spacing_minutes: 60
"""
    )

    settings = load_settings(
        tmp_path / "configs" / "factory.local.yaml",
        tmp_path / "configs" / "accounts.local.yaml",
        project_root=tmp_path,
    )
    pipeline = FactoryPipeline(settings)
    now = datetime(2026, 3, 7, 10, 0, tzinfo=UTC)

    for index in range(2):
        pipeline.queue.upsert(
            QueueJob(
                job_id=f"scheduled-{index}",
                mode="reddit_story_gameplay",
                source_type="reddit",
                state="scheduled",
                account_name="local-test",
                title="x",
                description="x",
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
                scheduled_for=f"2026-03-07T1{7 + index}:00:00+01:00",
                metadata={},
            )
        )

    assert pipeline._remaining_daily_capacity(now) == 1
