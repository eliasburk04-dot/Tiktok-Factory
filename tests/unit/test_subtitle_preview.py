from __future__ import annotations

from pathlib import Path

from tictoc_factory.config import load_settings
from tictoc_factory.subtitles import preview


def _build_preview_settings(tmp_path: Path):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "input" / "gameplay").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "work").mkdir(parents=True, exist_ok=True)
    factory_config = configs_dir / "factory.local.yaml"
    accounts_config = configs_dir / "accounts.local.yaml"
    factory_config.write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits: [nosleep]
providers:
  llm_provider: openai
  transcription_provider: sidecar
tts:
  provider: tone
subtitles:
  font_file: /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [30]
content_policy:
  max_posts_per_day: 1
  min_source_score: 10
"""
    )
    accounts_config.write_text(
        """
accounts:
  - name: local-test
    posting_windows: ["09:00-11:00"]
"""
    )
    return load_settings(factory_config, accounts_config, project_root=tmp_path)


def test_build_preview_story_produces_monotonic_word_timings() -> None:
    script, segments = preview._build_preview_story()

    assert len(script.segments) == 3
    assert len(segments) == 3
    assert segments[0].words
    assert segments[0].start == 0.0
    assert segments[-1].end > segments[0].end
    assert all(word.start < word.end for segment in segments for word in segment.words)
    assert all(
        segments[index].end <= segments[index + 1].start
        for index in range(len(segments) - 1)
    )


def test_preview_audio_and_background_use_expected_ffmpeg_filters(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], cwd: Path | None = None) -> None:
        commands.append(command)

    monkeypatch.setattr("tictoc_factory.subtitles.preview.run_command", fake_run_command)

    preview._render_preview_audio(tmp_path / "preview.wav", duration=4.2, sample_rate=44_100)
    preview._render_preview_background(tmp_path / "preview.mp4", duration=4.2, width=1080, height=1920)

    assert "anullsrc=r=44100:cl=mono" in commands[0]
    assert any("testsrc2=s=1080x1920:rate=30:duration=4.20" in value for value in commands[1])
    assert any("boxblur=2:1" in value for value in commands[1])


def test_render_subtitle_preview_prefers_existing_gameplay_clip(monkeypatch, tmp_path: Path) -> None:
    settings = _build_preview_settings(tmp_path)
    gameplay_path = settings.paths.gameplay_input / "clip-a.mp4"
    gameplay_path.write_bytes(b"clip")
    output_path = tmp_path / "artifacts" / "preview.mp4"
    captured: dict[str, Path] = {}

    def fake_generate_from_script(self, script, *, output_path: Path, segment_timings) -> Path:
        output_path.write_text("ass")
        return output_path

    def fake_render_preview_audio(output_path: Path, *, duration: float, sample_rate: int) -> None:
        output_path.write_bytes(b"wav")

    def fake_render_preview_background(output_path: Path, *, duration: float, width: int, height: int) -> None:
        raise AssertionError("background render should not be used when gameplay exists")

    def fake_compose_story_gameplay(
        self,
        *,
        gameplay_path: Path,
        subtitles_path: Path,
        audio_path: Path,
        intro_card_path: Path | None,
        output_path: Path,
    ) -> Path:
        captured["gameplay_path"] = gameplay_path
        captured["subtitles_path"] = subtitles_path
        captured["audio_path"] = audio_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mp4")
        return output_path

    monkeypatch.setattr("tictoc_factory.subtitles.preview.SubtitleGenerator.generate_from_script", fake_generate_from_script)
    monkeypatch.setattr("tictoc_factory.subtitles.preview._render_preview_audio", fake_render_preview_audio)
    monkeypatch.setattr("tictoc_factory.subtitles.preview._render_preview_background", fake_render_preview_background)
    monkeypatch.setattr("tictoc_factory.subtitles.preview.VideoComposer.compose_story_gameplay", fake_compose_story_gameplay)

    result = preview.render_subtitle_preview(settings, output_path=output_path)

    assert result == output_path
    assert captured["gameplay_path"] == gameplay_path
    assert captured["subtitles_path"].suffix == ".ass"
    assert captured["audio_path"].suffix == ".wav"


def test_render_subtitle_preview_generates_background_when_gameplay_missing(monkeypatch, tmp_path: Path) -> None:
    settings = _build_preview_settings(tmp_path)
    output_path = tmp_path / "artifacts" / "preview.mp4"
    captured: dict[str, Path] = {}

    def fake_generate_from_script(self, script, *, output_path: Path, segment_timings) -> Path:
        output_path.write_text("ass")
        return output_path

    def fake_render_preview_audio(output_path: Path, *, duration: float, sample_rate: int) -> None:
        output_path.write_bytes(b"wav")

    def fake_render_preview_background(output_path: Path, *, duration: float, width: int, height: int) -> None:
        captured["background_path"] = output_path
        output_path.write_bytes(b"bg")

    def fake_compose_story_gameplay(
        self,
        *,
        gameplay_path: Path,
        subtitles_path: Path,
        audio_path: Path,
        intro_card_path: Path | None,
        output_path: Path,
    ) -> Path:
        captured["gameplay_path"] = gameplay_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mp4")
        return output_path

    monkeypatch.setattr("tictoc_factory.subtitles.preview.SubtitleGenerator.generate_from_script", fake_generate_from_script)
    monkeypatch.setattr("tictoc_factory.subtitles.preview._render_preview_audio", fake_render_preview_audio)
    monkeypatch.setattr("tictoc_factory.subtitles.preview._render_preview_background", fake_render_preview_background)
    monkeypatch.setattr("tictoc_factory.subtitles.preview.VideoComposer.compose_story_gameplay", fake_compose_story_gameplay)

    result = preview.render_subtitle_preview(settings, output_path=output_path)

    assert result == output_path
    assert captured["gameplay_path"] == captured["background_path"]
