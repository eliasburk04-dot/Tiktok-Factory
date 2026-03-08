from __future__ import annotations

import json
from pathlib import Path

from tictoc_factory.models import (
    CompositionConfig,
    ScriptArtifact,
    StorySegment,
    SubtitleConfig,
    TranscriptSegment,
    WordTiming,
)
from tictoc_factory.subtitles.generator import SubtitleGenerator


def test_story_subtitles_render_as_centered_ass_with_wrapped_lines(tmp_path: Path) -> None:
    generator = SubtitleGenerator(SubtitleConfig(max_words_per_line=3, max_lines_per_caption=2), CompositionConfig())
    script = ScriptArtifact(
        hook="My roommate had a rule.",
        setup="Never open the basement door after midnight.",
        tension="Every night the handle rattled by itself.",
        payoff="Then the whisper came from inside the room.",
        cta="Follow for part two.",
        narration=(
            "My roommate had a rule. Never open the basement door after midnight. "
            "Every night the handle rattled by itself. Then the whisper came from inside the room. "
            "Follow for part two."
        ),
        summary="A basement rule becomes a whispering nightmare.",
        segments=[
            StorySegment(stage="hook", text="My roommate had a rule.", pause_after_ms=250),
            StorySegment(stage="context", text="Never open the basement door after midnight.", pause_after_ms=220),
            StorySegment(stage="final_twist", text="Then the whisper came from inside the room.", pause_after_ms=0),
        ],
    )
    output_path = tmp_path / "story.ass"

    generator.generate_from_script(
        script,
        output_path=output_path,
        segment_timings=[
            TranscriptSegment(start=0.0, end=1.2, text=script.segments[0].text),
            TranscriptSegment(start=1.45, end=3.1, text=script.segments[1].text),
            TranscriptSegment(start=3.3, end=4.7, text=script.segments[2].text),
        ],
    )

    contents = output_path.read_text()
    kinetic_payload = json.loads(output_path.with_suffix(".kinetic.json").read_text())

    assert "[V4+ Styles]" in contents
    assert "Style: Story,Montserrat Black" in contents
    assert "{\\an5\\pos(540,960)}" in contents
    assert "Never open the\\Nbasement door" in contents
    assert "Dialogue: 0,0:00:01.45,0:00:03.10,Story" in contents
    assert kinetic_payload["format"] == "kinetic_subtitles_v1"
    assert kinetic_payload["segments"][1]["words"][0]["text"] == "Never"


def test_story_subtitles_emit_companion_kinetic_manifest(tmp_path: Path) -> None:
    generator = SubtitleGenerator(SubtitleConfig(max_words_per_line=3, max_lines_per_caption=2), CompositionConfig())
    script = ScriptArtifact(
        hook="Never open the basement door.",
        setup="My roommate only said it once.",
        tension="Then I heard the lock turn.",
        payoff="The whisper already knew my name.",
        cta="Follow for more.",
        narration=(
            "Never open the basement door. My roommate only said it once. "
            "Then I heard the lock turn. The whisper already knew my name."
        ),
        summary="A basement warning turns personal.",
        segments=[
            StorySegment(stage="hook", text="Never open the basement door.", pause_after_ms=180),
            StorySegment(stage="final_twist", text="The whisper already knew my name.", pause_after_ms=0),
        ],
    )
    output_path = tmp_path / "story.ass"

    generator.generate_from_script(
        script,
        output_path=output_path,
        segment_timings=[
            TranscriptSegment(
                start=0.0,
                end=1.6,
                text=script.segments[0].text,
                words=[
                    WordTiming(start=0.0, end=0.25, text="Never"),
                    WordTiming(start=0.25, end=0.55, text="open"),
                    WordTiming(start=0.55, end=0.80, text="the"),
                    WordTiming(start=0.80, end=1.25, text="basement"),
                    WordTiming(start=1.25, end=1.60, text="door."),
                ],
            ),
            TranscriptSegment(
                start=1.8,
                end=3.55,
                text=script.segments[1].text,
                words=[
                    WordTiming(start=1.8, end=2.15, text="The"),
                    WordTiming(start=2.15, end=2.60, text="whisper"),
                    WordTiming(start=2.60, end=2.95, text="already"),
                    WordTiming(start=2.95, end=3.20, text="knew"),
                    WordTiming(start=3.20, end=3.40, text="my"),
                    WordTiming(start=3.40, end=3.55, text="name."),
                ],
            ),
        ],
    )

    payload = json.loads(output_path.with_suffix(".kinetic.json").read_text())

    assert payload["segments"][0]["text"] == "Never open the basement door."
    assert payload["segments"][0]["words"][3]["text"] == "basement"
    assert payload["segments"][1]["words"][1]["start"] == 2.15


def test_subtitle_generator_can_estimate_srt_timings_from_script_narration(tmp_path: Path) -> None:
    generator = SubtitleGenerator(SubtitleConfig(max_words_per_line=3), CompositionConfig())
    script = ScriptArtifact(
        hook="This line changes everything.",
        setup="The room was supposed to stay empty.",
        tension="Then the whisper came back.",
        payoff="It was already inside the house.",
        cta="Follow for more.",
        narration=(
            "This line changes everything. The room was supposed to stay empty. "
            "Then the whisper came back. It was already inside the house."
        ),
        summary="A whisper returns to an empty room.",
    )
    output_path = tmp_path / "story.srt"

    generator.generate_from_script(script, output_path=output_path, audio_duration=4.8)

    contents = output_path.read_text()

    assert "1\n00:00:00,000 -->" in contents
    assert "This line changes" in contents
    assert "everything." in contents


def test_subtitle_generator_handles_missing_transcript_segments(tmp_path: Path) -> None:
    generator = SubtitleGenerator(SubtitleConfig(), CompositionConfig())
    output_path = tmp_path / "empty.srt"

    generator.generate_from_segments([], clip_start=0.0, clip_end=3.0, output_path=output_path)

    assert "No transcript available." in output_path.read_text()
