from __future__ import annotations

from pathlib import Path

from tictoc_factory.config import load_settings
from tictoc_factory.pipeline.orchestrator import FactoryPipeline, PipelineRunResult


def test_regenerate_batch_clears_generated_artifacts_before_running(tmp_path: Path, monkeypatch) -> None:
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
    stale_files = [
        settings.paths.output_videos / "old.mp4",
        settings.paths.output_audio / "old.wav",
        settings.paths.output_subtitles / "old.ass",
        settings.paths.output_scripts / "old.json",
        settings.paths.queue_jobs / "old.json",
    ]
    for path in stale_files:
        path.write_text("stale")

    calls: list[str | None] = []

    def fake_run_cycle(*, now_iso: str | None = None) -> PipelineRunResult:
        calls.append(now_iso)
        return PipelineRunResult(discovered_jobs=1, processed_jobs=1, scheduled_jobs=1)

    monkeypatch.setattr(pipeline, "run_cycle", fake_run_cycle)

    result = pipeline.regenerate_batch(now_iso="2026-03-07T09:00:00+00:00")

    assert result.processed_jobs == 1
    assert calls == ["2026-03-07T09:00:00+00:00"]
    assert not any(path.exists() for path in stale_files)
