from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from tictoc_factory.config import load_settings
from tictoc_factory.models import ContentCandidate, HookOutput, ScriptArtifact
from tictoc_factory.pipeline.orchestrator import FactoryPipeline


class FakeCreativeDirector:
    def generate_story_package(self, *, candidate, mode, clip=None):
        hook = HookOutput(template_id="openai-generic", text="This one line changes everything.", style_tag="shock")
        script = ScriptArtifact(
            hook=hook.text,
            setup="Setup line.",
            tension="Tension line.",
            payoff="Payoff line.",
            cta="Follow for more.",
            narration="This one line changes everything. Setup line. Tension line. Payoff line. Follow for more.",
            summary="Summary line.",
        )
        return hook, script, {"provider": "openai", "model": "gpt-test"}


def test_pipeline_rebuilds_reddit_story_with_local_pacing_when_openai_creative_is_available(tmp_path: Path) -> None:
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
    pipeline.creative_director = cast(Any, FakeCreativeDirector())
    candidate = ContentCandidate(
        id="story-hot",
        subreddit="nosleep",
        title="I opened the attic door and something whispered my name",
        body="I never told anyone about the locked attic until the whisper came back the second night.",
        score=18200,
        num_comments=942,
        created_utc=1730985600,
    )

    hook, script, metadata = pipeline._generate_creative_package(candidate=candidate, mode="reddit_story_gameplay", clip=None)

    # V4: reddit_story_gameplay always uses verbatim text, never the AI creative director
    assert metadata["provider"] == "verbatim"
    assert script.segments
    # Hook should be the original Reddit title verbatim
    assert script.segments[0].text == candidate.title
    # Narration should contain the original body text verbatim
    assert candidate.body in script.narration
