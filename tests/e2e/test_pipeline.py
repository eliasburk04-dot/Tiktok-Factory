from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tictoc_factory.config import load_settings
from tictoc_factory.pipeline.orchestrator import FactoryPipeline


def _run_ffmpeg(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def _make_test_video(path: Path, duration: int, color: str) -> None:
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1280x720:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _extract_frame(video_path: Path, timestamp: float, output_path: Path) -> None:
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{timestamp:.2f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(output_path),
        ]
    )


def test_e2e_pipeline_creates_composed_artifact(tmp_path: Path, fixture_dir: Path) -> None:
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

    (tmp_path / "configs" / ".env").write_text("OPENAI_API_KEY=\n")
    (tmp_path / "configs" / "factory.local.yaml").write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits: [nosleep, confessions]
providers:
  discovery_provider: fixture
  llm_provider: openai
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
tts:
  provider: auto
  system_voice: Samantha
  openai_voice: alloy
  speech_speed: 1.02
  sentence_pause_ms: 140
subtitles:
  max_words_per_line: 4
  max_lines_per_caption: 2
  highlight_color: "#ffd54a"
  active_word_scale: 1.12
  pop_animation_ms: 0
story_pacing:
  suspense_segments: 5
  minimum_total_words: 20
  target_duration_seconds_min: 15
  target_duration_seconds_max: 25
  intro_pause_ms: 180
  mid_pause_ms: 140
  final_pause_ms: 90
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [25]
content_policy:
  max_posts_per_day: 1
  min_source_score: 10
  preferred_modes: [reddit_story_gameplay]
composition:
  layout: split
  subtitles_style: bold_box
reddit_card:
  duration_seconds: 1.25
"""
    )
    (tmp_path / "configs" / "accounts.local.yaml").write_text(
        """
accounts:
  - name: local-test
    enabled: true
    uploader: local_archive
    posting_windows:
      - "09:00-11:00"
    timezone: UTC
    template_tags: ["story", "clip"]
"""
    )
    (tmp_path / "data" / "input" / "reddit_fixture.json").write_text(
        (fixture_dir / "reddit_posts.json").read_text()
    )
    podcast_media = tmp_path / "data" / "input" / "longform" / "podcasts_streams" / "podcast.mp4"
    gameplay_media = tmp_path / "data" / "input" / "gameplay_longform" / "gameplay-master.mp4"
    stale_output = tmp_path / "data" / "output" / "videos" / "stale.mp4"
    stale_output.write_text("old")
    _make_test_video(podcast_media, duration=54, color="navy")
    _make_test_video(gameplay_media, duration=54, color="green")
    (podcast_media.with_suffix(".segments.json")).write_text(
        (fixture_dir / "podcast_segments.json").read_text()
    )

    settings = load_settings(
        tmp_path / "configs" / "factory.local.yaml",
        tmp_path / "configs" / "accounts.local.yaml",
        project_root=tmp_path,
        env_path=tmp_path / "configs" / ".env",
    )
    pipeline = FactoryPipeline(settings)

    result = pipeline.regenerate_batch(now_iso="2026-03-07T09:00:00+00:00")

    assert result.processed_jobs >= 1
    output_videos = list((tmp_path / "data" / "output" / "videos").glob("*.mp4"))
    output_scripts = list((tmp_path / "data" / "output" / "scripts").glob("*.json"))
    queue_jobs = list((tmp_path / "data" / "queue" / "jobs").glob("*.json"))
    analytics_lines = (tmp_path / "data" / "analytics" / "events.jsonl").read_text().strip().splitlines()

    assert output_videos
    assert stale_output not in output_videos
    assert output_scripts
    assert queue_jobs
    assert analytics_lines
    assert list((tmp_path / "data" / "input" / "gameplay").glob("*.mp4"))
    assert list((tmp_path / "data" / "work").glob("*post-card.png"))
    kinetic_overlays = list((tmp_path / "data" / "work").glob("*kinetic-*.png"))
    assert kinetic_overlays
    assert kinetic_overlays[0].read_bytes() != kinetic_overlays[-1].read_bytes()
    overlay_tracks = list((tmp_path / "data" / "work").glob("*overlay-track.mov"))
    assert overlay_tracks
    kinetic_manifest_paths = list((tmp_path / "data" / "output" / "subtitles").glob("*.kinetic.json"))
    assert kinetic_manifest_paths
    kinetic_payload = json.loads(kinetic_manifest_paths[0].read_text())
    timed_words = [
        word
        for segment in kinetic_payload["segments"]
        for word in segment.get("words", [])
        if float(word["start"]) >= 1.35
    ]
    assert len(timed_words) >= 2
    first_time = min(float(timed_words[0]["start"]) + 0.05, float(timed_words[0]["end"]) - 0.01)
    second_time = min(float(timed_words[1]["start"]) + 0.05, float(timed_words[1]["end"]) - 0.01)
    frame_one = tmp_path / "data" / "work" / "kinetic-frame-one.png"
    frame_two = tmp_path / "data" / "work" / "kinetic-frame-two.png"
    _extract_frame(output_videos[0], first_time, frame_one)
    _extract_frame(output_videos[0], second_time, frame_two)
    assert frame_one.read_bytes() != frame_two.read_bytes()
    payload = json.loads(output_scripts[0].read_text())
    assert payload["hook"]
    assert payload["segments"]
