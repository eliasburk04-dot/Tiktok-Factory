from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

from PIL import Image

from tictoc_factory.media.composer import VideoComposer
from tictoc_factory.models import CompositionConfig, ContentCandidate, RedditCardConfig, SubtitleConfig, TranscriptSegment, WordTiming


def test_story_gameplay_uses_fullscreen_gameplay_and_centered_subtitles(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], cwd: Path | None = None) -> None:
        commands.append(command)

    monkeypatch.setattr("tictoc_factory.media.composer.run_command", fake_run_command)

    composer = VideoComposer(CompositionConfig(target_fps=24), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    gameplay_path = tmp_path / "gameplay.mp4"
    subtitles_path = tmp_path / "story.ass"
    audio_path = tmp_path / "story.wav"
    subtitle_track_path = tmp_path / "story-overlay.mov"
    intro_card_path = tmp_path / "story-card.png"
    output_path = tmp_path / "story-output.mp4"
    subtitles_path.write_text(
        """
[Script Info]
ScriptType: v4.00+

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.80,Story,,0,0,0,,{\\an5\\pos(540,1075)}One line.\\NSecond line.
""".strip()
        + "\n"
    )
    intro_card_path.write_bytes(b"png")
    monkeypatch.setattr(composer, "_build_story_overlay_track", lambda _path: subtitle_track_path)

    composer.compose_story_gameplay(
        gameplay_path=gameplay_path,
        subtitles_path=subtitles_path,
        audio_path=audio_path,
        intro_card_path=intro_card_path,
        output_path=output_path,
    )

    assert len(commands) == 1
    command = commands[0]
    assert str(gameplay_path) in command
    assert str(audio_path) in command
    assert str(subtitle_track_path) in command
    assert str(output_path) == command[-1]
    assert command.count("-loop") == 1
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" in filter_complex
    assert "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" in filter_complex
    assert "fps=24" in filter_complex
    # V4: zoompan and runtime setpts removed — gameplay is pre-accelerated
    assert "zoompan" not in filter_complex
    assert "setpts" not in filter_complex
    assert "fade=in:st=0:d=0.18:alpha=1" in filter_complex
    assert "fade=out" in filter_complex
    assert "between(t,0,2.50)" in filter_complex
    assert "vstack" not in filter_complex
    assert command[command.index("-r") + 1] == "24"


def test_story_gameplay_mixes_card_transition_swoosh_when_configured(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], cwd: Path | None = None) -> None:
        commands.append(command)

    monkeypatch.setattr("tictoc_factory.media.composer.run_command", fake_run_command)

    swoosh_path = tmp_path / "universfield-swoosh-06-351021.mp3"
    swoosh_path.write_bytes(b"ID3")

    composer = VideoComposer(
        CompositionConfig(),
        SubtitleConfig(),
        RedditCardConfig(
            transition_sfx_path=str(swoosh_path),
            transition_sfx_volume=0.72,
        ),
        tmp_path / "work",
    )
    gameplay_path = tmp_path / "gameplay.mp4"
    subtitles_path = tmp_path / "story.ass"
    audio_path = tmp_path / "story.wav"
    intro_card_path = tmp_path / "story-card.png"
    output_path = tmp_path / "story-output.mp4"
    intro_card_path.write_bytes(b"png")
    subtitles_path.write_text("[Script Info]\nScriptType: v4.00+\n")
    monkeypatch.setattr(composer, "_build_story_overlay_track", lambda _path: None)

    composer.compose_story_gameplay(
        gameplay_path=gameplay_path,
        subtitles_path=subtitles_path,
        audio_path=audio_path,
        intro_card_path=intro_card_path,
        output_path=output_path,
    )

    assert len(commands) == 1
    command = commands[0]
    assert str(swoosh_path) in command
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "fade=in:st=0:d=0.18:alpha=1" in filter_complex
    assert "fade=out:st=2.10:d=0.40:alpha=1" in filter_complex
    assert "asplit=2[sfx_intro_src][sfx_outro_src]" in filter_complex
    assert "volume=0.72,adelay=0|0[sfx_intro]" in filter_complex
    assert "volume=0.72,adelay=2100|2100[sfx_outro]" in filter_complex
    assert "amix=inputs=3:normalize=0:dropout_transition=0" in filter_complex
    assert command[command.index("-map") + 3] == "[a]"


def test_render_reddit_post_card_creates_centered_dark_mode_card(tmp_path: Path) -> None:
    composer = VideoComposer(CompositionConfig(), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    candidate = ContentCandidate(
        id="story-hot",
        subreddit="scarystories",
        title="My roommate had a rule about the basement door",
        body=(
            "He said never open it after midnight. "
            "The first night I ignored him, something whispered my full name from downstairs."
        ),
        score=18200,
        num_comments=942,
        created_utc=1730985600,
    )
    output_path = tmp_path / "reddit-card.png"

    composer.render_reddit_post_card(candidate, output_path)

    assert output_path.exists()
    image = Image.open(output_path)
    assert image.size == (1080, 1920)
    bbox = image.getbbox()
    assert bbox is not None
    center_pixel = cast(tuple[int, int, int, int], image.getpixel((540, 960)))
    assert center_pixel[3] > 0


def test_render_reddit_post_card_strips_navigation_links_from_preview(tmp_path: Path, monkeypatch) -> None:
    composer = VideoComposer(CompositionConfig(), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    candidate = ContentCandidate(
        id="story-links",
        subreddit="nosleep",
        title="My father raised me in a mountain cabin.",
        body=(
            "**Part I** - [Part II](https://www.reddit.com/r/nosleep/comments/example/part_ii/) "
            "- [Part III](https://www.reddit.com/r/nosleep/comments/example/part_iii/)\n\n"
            "The floorboards started breathing beneath the bed."
        ),
        score=18200,
        num_comments=942,
        created_utc=1730985600,
    )
    captured: dict[str, str] = {}

    def fake_fit_card_lines(value: str, *args, **kwargs) -> list[str]:
        captured["body"] = value
        return ["Preview line"]

    monkeypatch.setattr(composer, "_fit_card_lines", fake_fit_card_lines)

    composer.render_reddit_post_card(candidate, tmp_path / "reddit-card.png")

    assert "http" not in captured["body"]
    assert "Part II" not in captured["body"]
    assert captured["body"] == "The floorboards started breathing beneath the bed."


def test_fit_card_lines_truncates_body_to_available_height(tmp_path: Path) -> None:
    composer = VideoComposer(CompositionConfig(), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    font = composer._card_font(composer.reddit_card_config.body_font_size)
    lines = composer._fit_card_lines(
        (
            "This is a deliberately long Reddit body that should never push the preview text "
            "through the bottom edge of the intro card because the footer needs its own space "
            "and the visible body copy must truncate cleanly."
        ),
        font,
        max_width=520,
        max_height=76,
        max_lines=7,
        spacing=9,
    )

    assert lines
    assert composer._measure_multiline_height(lines, font, spacing=9) <= 76
    assert lines[-1].endswith("...")


def test_story_overlays_render_kinetic_word_states_from_manifest(tmp_path: Path) -> None:
    composer = VideoComposer(CompositionConfig(), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    subtitles_path = tmp_path / "story.ass"
    subtitles_path.write_text(
        """
[Script Info]
ScriptType: v4.00+
""".strip()
        + "\n"
    )
    subtitles_path.with_suffix(".kinetic.json").write_text(
        json.dumps(
            {
                "format": "kinetic_subtitles_v1",
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.6,
                        "text": "Never open the basement door.",
                        "words": [
                            {"start": 0.0, "end": 0.30, "text": "Never"},
                            {"start": 0.30, "end": 0.65, "text": "open"},
                            {"start": 0.65, "end": 0.90, "text": "the"},
                            {"start": 0.90, "end": 1.25, "text": "basement"},
                            {"start": 1.25, "end": 1.60, "text": "door."},
                        ],
                    }
                ],
            }
        )
    )

    overlays = composer._load_story_overlays(subtitles_path)
    overlay_track_path = composer._build_story_overlay_track(subtitles_path)
    assert overlay_track_path is not None
    frame_one = tmp_path / "frame-one.png"
    frame_two = tmp_path / "frame-two.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "0.10", "-i", str(overlay_track_path), "-frames:v", "1", str(frame_one)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "1.30", "-i", str(overlay_track_path), "-frames:v", "1", str(frame_two)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert len(overlays) >= 10
    assert overlays[0].start == 0.0
    assert overlays[-1].end == 1.6
    assert overlays[0].image_path.exists()
    assert overlays[-1].image_path.exists()
    assert overlay_track_path.exists()
    assert frame_one.exists()
    assert frame_two.exists()
    assert overlays[0].image_path.read_bytes() != overlays[-1].image_path.read_bytes()
    assert frame_one.read_bytes() != frame_two.read_bytes()


def test_wrap_segment_words_tracks_late_words_in_visible_window(tmp_path: Path) -> None:
    composer = VideoComposer(
        CompositionConfig(),
        SubtitleConfig(max_words_per_line=3, max_lines_per_caption=2),
        RedditCardConfig(),
        tmp_path / "work",
    )
    segment = TranscriptSegment(
        start=0.0,
        end=3.6,
        text="One two three four five six seven eight nine ten.",
        words=[
            WordTiming(start=0.00, end=0.30, text="One"),
            WordTiming(start=0.30, end=0.60, text="two"),
            WordTiming(start=0.60, end=0.90, text="three"),
            WordTiming(start=0.90, end=1.20, text="four"),
            WordTiming(start=1.20, end=1.50, text="five"),
            WordTiming(start=1.50, end=1.80, text="six"),
            WordTiming(start=1.80, end=2.10, text="seven"),
            WordTiming(start=2.10, end=2.40, text="eight"),
            WordTiming(start=2.40, end=2.80, text="nine"),
            WordTiming(start=2.80, end=3.60, text="ten."),
        ],
    )

    first_rows = composer._wrap_segment_words(segment, active_word_index=0)
    late_rows = composer._wrap_segment_words(segment, active_word_index=8)

    assert first_rows == [[0, 1, 2], [3, 4, 5]]
    assert late_rows == [[4, 5, 6], [7, 8, 9]]


def test_render_kinetic_overlay_highlights_only_the_active_word_glyphs(tmp_path: Path) -> None:
    composer = VideoComposer(
        CompositionConfig(),
        SubtitleConfig(
            highlight_color="#39E0FF",
            active_text_color="#111111",
            caption_background_color="#101418CC",
        ),
        RedditCardConfig(),
        tmp_path / "work",
    )
    output_path = tmp_path / "active-word.png"
    segment = TranscriptSegment(
        start=0.0,
        end=1.4,
        text="Then the whisper said",
        words=[
            WordTiming(start=0.00, end=0.25, text="Then"),
            WordTiming(start=0.25, end=0.45, text="the"),
            WordTiming(start=0.45, end=0.95, text="whisper"),
            WordTiming(start=0.95, end=1.40, text="said"),
        ],
    )

    composer._render_kinetic_overlay(
        segment,
        active_word_index=2,
        output_path=output_path,
        scale=composer.subtitle_config.active_word_scale,
    )

    image = Image.open(output_path).convert("RGBA")
    highlight_pixels = 0
    highlight_bounds: list[int] | None = None
    pixels = image.load()
    assert pixels is not None
    for y_position in range(image.height):
        for x_position in range(image.width):
            red, green, blue, alpha = cast(tuple[int, int, int, int], pixels[x_position, y_position])
            if alpha == 0:
                continue
            if green >= 170 and blue >= 220 and red <= 110:
                highlight_pixels += 1
                if highlight_bounds is None:
                    highlight_bounds = [x_position, y_position, x_position, y_position]
                else:
                    highlight_bounds[0] = min(highlight_bounds[0], x_position)
                    highlight_bounds[1] = min(highlight_bounds[1], y_position)
                    highlight_bounds[2] = max(highlight_bounds[2], x_position)
                    highlight_bounds[3] = max(highlight_bounds[3], y_position)

    assert highlight_bounds is not None
    highlight_area = (highlight_bounds[2] - highlight_bounds[0] + 1) * (highlight_bounds[3] - highlight_bounds[1] + 1)

    assert highlight_pixels > 200
    assert (highlight_pixels / highlight_area) < 0.45


def test_kinetic_overlays_respect_silent_gap_between_v2_segments(tmp_path: Path) -> None:
    composer = VideoComposer(CompositionConfig(), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    subtitles_path = tmp_path / "story.ass"
    subtitles_path.write_text("[Script Info]\nScriptType: v4.00+\n")
    subtitles_path.with_suffix(".kinetic.json").write_text(
        json.dumps(
            {
                "format": "kinetic_subtitles_v2",
                "segments": [
                    {
                        "start": 0.0,
                        "end": 0.82,
                        "text": "First line.",
                        "words": [
                            {"start": 0.0, "end": 0.30, "text": "First"},
                            {"start": 0.30, "end": 0.82, "text": "line."},
                        ],
                    },
                    {
                        "start": 1.07,
                        "end": 1.90,
                        "text": "Second line.",
                        "words": [
                            {"start": 1.07, "end": 1.35, "text": "Second"},
                            {"start": 1.35, "end": 1.90, "text": "line."},
                        ],
                    },
                ],
            }
        )
    )

    overlays = composer._load_story_overlays(subtitles_path)

    assert overlays
    assert not any(overlay.start < 0.95 < overlay.end for overlay in overlays)


def test_compose_longform_clip_uses_configured_target_fps(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], cwd: Path | None = None) -> None:
        commands.append(command)

    monkeypatch.setattr("tictoc_factory.media.composer.run_command", fake_run_command)

    composer = VideoComposer(CompositionConfig(target_fps=24), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    clip_path = tmp_path / "clip.mp4"
    subtitles_path = tmp_path / "clip.ass"
    output_path = tmp_path / "output.mp4"

    composer.compose_longform_clip(
        clip_path=clip_path,
        subtitles_path=subtitles_path,
        output_path=output_path,
    )

    assert len(commands) == 1
    command = commands[0]
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "fps=24" in filter_complex
    assert command[command.index("-r") + 1] == "24"


def test_compose_hybrid_uses_configured_target_fps(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], cwd: Path | None = None) -> None:
        commands.append(command)

    monkeypatch.setattr("tictoc_factory.media.composer.run_command", fake_run_command)

    composer = VideoComposer(CompositionConfig(target_fps=24), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
    clip_path = tmp_path / "clip.mp4"
    gameplay_path = tmp_path / "gameplay.mp4"
    subtitles_path = tmp_path / "hybrid.ass"
    output_path = tmp_path / "hybrid.mp4"

    composer.compose_hybrid(
        clip_path=clip_path,
        gameplay_path=gameplay_path,
        subtitles_path=subtitles_path,
        output_path=output_path,
    )

    assert len(commands) == 1
    command = commands[0]
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "fps=24" in filter_complex
    assert command[command.index("-r") + 1] == "24"
