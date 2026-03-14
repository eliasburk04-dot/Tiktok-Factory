from __future__ import annotations

from pathlib import Path

from ..media.composer import VideoComposer
from ..models import FactorySettings, ScriptArtifact, StorySegment, TranscriptSegment, WordTiming
from ..subtitles.generator import SubtitleGenerator
from ..utils.process import run_command


def render_subtitle_preview(
    settings: FactorySettings,
    *,
    output_path: Path,
    gameplay_path: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview_stem = output_path.stem
    subtitle_path = output_path.parent / f"{preview_stem}.ass"
    audio_path = output_path.parent / f"{preview_stem}.wav"
    background_path = output_path.parent / f"{preview_stem}-background.mp4"
    script, segment_timings = _build_preview_story()

    SubtitleGenerator(settings.subtitles, settings.composition).generate_from_script(
        script,
        output_path=subtitle_path,
        segment_timings=segment_timings,
    )
    duration = segment_timings[-1].end + 0.25
    _render_preview_audio(audio_path, duration=duration, sample_rate=settings.tts.sample_rate_hz)
    source_path = gameplay_path or _first_preview_gameplay_clip(settings)
    if source_path is None:
        _render_preview_background(background_path, duration=duration, width=settings.composition.width, height=settings.composition.height)
        source_path = background_path

    VideoComposer(
        settings.composition,
        settings.subtitles,
        settings.reddit_card,
        settings.paths.work,
    ).compose_story_gameplay(
        gameplay_path=source_path,
        subtitles_path=subtitle_path,
        audio_path=audio_path,
        intro_card_path=None,
        output_path=output_path,
    )
    return output_path


def _build_preview_story() -> tuple[ScriptArtifact, list[TranscriptSegment]]:
    preview_lines = [
        "My dad said the tree line started moving after midnight.",
        "I laughed until one of the shadows said my name.",
        "That was when I realized the front door had been open the whole time.",
    ]
    script = ScriptArtifact(
        hook=preview_lines[0],
        setup=preview_lines[1],
        tension="",
        payoff=preview_lines[2],
        cta="Follow for more stories like this.",
        narration=" ".join([*preview_lines, "Follow for more stories like this."]),
        summary="Preview clip for subtitle timing and styling.",
        segments=[
            StorySegment(stage="hook", text=preview_lines[0], pause_after_ms=160),
            StorySegment(stage="escalation", text=preview_lines[1], pause_after_ms=150),
            StorySegment(stage="final_twist", text=preview_lines[2], pause_after_ms=0),
        ],
    )
    segments: list[TranscriptSegment] = []
    cursor = 0.0
    for index, line in enumerate(preview_lines):
        word_timings: list[WordTiming] = []
        line_cursor = cursor
        for token in line.split():
            duration = 0.18 + min(len(token), 8) * 0.028
            word_timings.append(WordTiming(start=line_cursor, end=line_cursor + duration, text=token))
            line_cursor += duration
            if token.endswith((".", "!", "?")):
                line_cursor += 0.18
            else:
                line_cursor += 0.05
        segments.append(
            TranscriptSegment(
                start=cursor,
                end=line_cursor,
                text=line,
                words=word_timings,
            )
        )
        cursor = line_cursor + (0.18 if index < len(preview_lines) - 1 else 0.0)
    return script, segments


def _render_preview_audio(output_path: Path, *, duration: float, sample_rate: int) -> None:
    run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            f"{duration:.2f}",
            str(output_path),
        ]
    )


def _render_preview_background(output_path: Path, *, duration: float, width: int, height: int) -> None:
    run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={width}x{height}:rate=30:duration={duration:.2f}",
            "-vf",
            "eq=contrast=1.08:saturation=0.8,boxblur=2:1,format=yuv420p",
            "-an",
            str(output_path),
        ]
    )


def _first_preview_gameplay_clip(settings: FactorySettings) -> Path | None:
    gameplay_candidates = sorted(settings.paths.gameplay_input.glob("*.mp4"))
    return gameplay_candidates[0] if gameplay_candidates else None
