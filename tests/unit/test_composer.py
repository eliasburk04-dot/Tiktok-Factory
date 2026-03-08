from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

from PIL import Image

from tictoc_factory.media.composer import VideoComposer
from tictoc_factory.models import CompositionConfig, ContentCandidate, RedditCardConfig, SubtitleConfig


def test_story_gameplay_uses_fullscreen_gameplay_and_centered_subtitles(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], cwd: Path | None = None) -> None:
        commands.append(command)

    monkeypatch.setattr("tictoc_factory.media.composer.run_command", fake_run_command)

    composer = VideoComposer(CompositionConfig(), SubtitleConfig(), RedditCardConfig(), tmp_path / "work")
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
    # V4: zoompan and runtime setpts removed — gameplay is pre-accelerated
    assert "zoompan" not in filter_complex
    assert "setpts" not in filter_complex
    assert "fade=out" in filter_complex
    assert "between(t,0,2.50)" in filter_complex
    assert "vstack" not in filter_complex


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
