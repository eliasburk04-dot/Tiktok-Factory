from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from ..models import CompositionConfig, ScriptArtifact, SubtitleConfig, TranscriptSegment, WordTiming
from ..utils.files import atomic_write_json, atomic_write_text
from ..utils.text import chunk_words
from .layout import build_caption_rows, split_caption_segments


def _format_srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def _format_ass_timestamp(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{whole_seconds:02}.{centiseconds:02}"


class SubtitleGenerator:
    def __init__(self, config: SubtitleConfig, composition: CompositionConfig) -> None:
        self.config = config
        self.composition = composition

    def generate_from_script(
        self,
        script: ScriptArtifact,
        *,
        output_path: Path,
        segment_timings: Sequence[TranscriptSegment] | None = None,
        audio_duration: float | None = None,
    ) -> Path:
        source_segments = [
            segment if segment.words else segment.model_copy(update={"words": self._estimate_word_timings(segment)})
            for segment in (segment_timings or self._estimate_script_segments(script, audio_duration=audio_duration))
        ]
        display_segments = split_caption_segments(source_segments, self.config)
        if output_path.suffix.lower() == ".ass":
            atomic_write_text(output_path, self._build_story_ass(display_segments))
            atomic_write_json(output_path.with_suffix(".kinetic.json"), self._build_story_kinetic_payload(display_segments))
            return output_path

        lines = []
        for index, segment in enumerate(display_segments, start=1):
            lines.append(
                f"{index}\n"
                f"{_format_srt_timestamp(segment.start)} --> {_format_srt_timestamp(segment.end)}\n"
                f"{self._wrap_text(segment.text)}\n"
            )
        atomic_write_text(output_path, "\n".join(lines).strip() + "\n")
        return output_path

    def generate_from_segments(
        self,
        segments: Iterable[TranscriptSegment],
        *,
        clip_start: float,
        clip_end: float,
        output_path: Path,
    ) -> Path:
        relevant = [
            item
            for item in segments
            if item.end >= clip_start and item.start <= clip_end and item.text.strip()
        ]
        if not relevant:
            atomic_write_text(
                output_path,
                "1\n00:00:00,000 --> 00:00:03,000\nNo transcript available.\n",
            )
            return output_path
        lines = []
        for index, segment in enumerate(relevant, start=1):
            start = max(segment.start, clip_start) - clip_start
            end = min(segment.end, clip_end) - clip_start
            lines.append(
                f"{index}\n"
                f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n"
                f"{self._wrap_text(segment.text, max_lines=self.config.max_lines_per_caption)}\n"
            )
        atomic_write_text(output_path, "\n".join(lines).strip() + "\n")
        return output_path

    def _estimate_script_segments(self, script: ScriptArtifact, *, audio_duration: float | None) -> list[TranscriptSegment]:
        text_chunks = [segment.text for segment in script.segments] or chunk_words(script.narration, chunk_size=8)
        if not text_chunks:
            return [TranscriptSegment(start=0.0, end=2.0, text="No narration available.")]
        duration = audio_duration or max(len(script.narration.split()) * 0.5, len(text_chunks) * 1.4)
        total_words = sum(len(chunk.split()) for chunk in text_chunks)
        cursor = 0.0
        timed_segments: list[TranscriptSegment] = []
        for chunk in text_chunks:
            proportion = len(chunk.split()) / max(total_words, 1)
            chunk_duration = max(1.1, duration * proportion)
            timed_segments.append(TranscriptSegment(start=cursor, end=min(cursor + chunk_duration, duration), text=chunk))
            cursor += chunk_duration
        if timed_segments:
            timed_segments[-1] = TranscriptSegment(
                start=timed_segments[-1].start,
                end=max(timed_segments[-1].end, duration),
                text=timed_segments[-1].text,
                words=timed_segments[-1].words,
            )
        return timed_segments

    def _build_story_kinetic_payload(self, segments: Sequence[TranscriptSegment]) -> dict[str, object]:
        return {
            "format": "kinetic_subtitles_v2",
            "theme": {
                "font_name": self.config.font_name,
                "font_size": self.config.font_size,
                "highlight_color": self.config.highlight_color,
                "position_y": self.config.position_y,
            },
            "segments": [segment.model_dump(mode="json") for segment in segments],
        }

    def _build_story_ass(self, segments: Sequence[TranscriptSegment]) -> str:
        x_position = self.composition.width // 2
        y_position = round(self.composition.height * self.config.position_y)
        header = "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                f"PlayResX: {self.composition.width}",
                f"PlayResY: {self.composition.height}",
                "WrapStyle: 2",
                "ScaledBorderAndShadow: yes",
                "",
                "[V4+ Styles]",
                (
                    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
                ),
                (
                    "Style: Story,"
                    f"{self.config.font_name},"
                    f"{self.config.font_size},"
                    "&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
                    f"{self.config.outline},{self.config.shadow},5,{self.config.margin_horizontal},{self.config.margin_horizontal},0,1"
                ),
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            ]
        )
        lines = [
            (
                "Dialogue: 0,"
                f"{_format_ass_timestamp(segment.start)},{_format_ass_timestamp(segment.end)},Story,,0,0,0,,"
                f"{{\\an5\\pos({x_position},{y_position})}}{self._wrap_segment_text(segment, ass=True)}"
            )
            for segment in segments
        ]
        return f"{header}\n" + "\n".join(lines) + "\n"

    def _estimate_word_timings(self, segment: TranscriptSegment) -> list[WordTiming]:
        tokens = segment.text.split()
        if not tokens:
            return []
        total_duration = max(segment.end - segment.start, 0.05 * len(tokens))
        word_duration = total_duration / max(len(tokens), 1)
        words: list[WordTiming] = []
        cursor = segment.start
        for index, token in enumerate(tokens):
            word_end = segment.end if index == len(tokens) - 1 else cursor + word_duration
            words.append(WordTiming(start=cursor, end=word_end, text=token))
            cursor = word_end
        return words

    def _wrap_text(self, text: str, *, ass: bool = False, max_lines: int | None = None) -> str:
        words = text.split()
        rows = build_caption_rows(words, self.config)
        if max_lines is not None:
            rows = rows[:max_lines]
        lines = [" ".join(words[index] for index in row) for row in rows]
        separator = "\\N" if ass else "\n"
        return separator.join(lines)

    def _wrap_segment_text(self, segment: TranscriptSegment, *, ass: bool = False) -> str:
        if not segment.words:
            return self._wrap_text(segment.text, ass=ass)
        tokens = [word.text for word in segment.words]
        rows = build_caption_rows(tokens, self.config)
        lines = [" ".join(tokens[index] for index in row) for row in rows]
        separator = "\\N" if ass else "\n"
        return separator.join(lines)
