from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

from ..models import CompositionConfig, ContentCandidate, RedditCardConfig, SubtitleConfig, TranscriptSegment
from ..subtitles.layout import build_caption_rows
from ..utils.files import atomic_write_text, load_json
from ..utils.process import run_command
from ..utils.text import normalize_spacing, sanitize_narration_text


def _subtitle_style(config: CompositionConfig, *, placement: str = "bottom") -> str:
    if placement == "center":
        return (
            "FontName=DejaVu Sans,"
            "FontSize=18,"
            "PrimaryColour=&H00FFFFFF&,"
            "BorderStyle=1,"
            "Outline=2,"
            "Shadow=0,"
            "Alignment=5,"
            "MarginV=0"
        )
    return (
        "FontName=DejaVu Sans,"
        "FontSize=18,"
        "PrimaryColour=&H00FFFFFF&,"
        "BackColour=&H80000000&,"
        "BorderStyle=4,"
        "Outline=1,"
        "Alignment=2,"
        "MarginV=40"
    )


def _format_drawtext_timestamp(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)


@dataclass(frozen=True)
class SubtitleOverlay:
    start: float
    end: float
    image_path: Path


@dataclass(frozen=True)
class KineticWordSlot:
    word_index: int
    text: str
    slot_width: float
    slot_height: float


@dataclass(frozen=True)
class KineticRowLayout:
    words: list[KineticWordSlot]
    width: float
    height: float


def _subtitle_font(config: CompositionConfig, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        config.font_file,
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, font_size)
    return ImageFont.load_default()


def _color_with_alpha(value: str, alpha: int | None = None) -> tuple[int, int, int, int]:
    rgba_value = ImageColor.getcolor(value, "RGBA")
    if isinstance(rgba_value, tuple):
        red, green, blue, current_alpha = rgba_value
    else:
        red = green = blue = rgba_value
        current_alpha = 255
    return (red, green, blue, current_alpha if alpha is None else alpha)


def _render_subtitle_overlay(
    text: str,
    output_path: Path,
    config: CompositionConfig,
    subtitle_config: SubtitleConfig,
) -> None:
    image = Image.new("RGBA", (config.width, config.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _subtitle_font(config, font_size=subtitle_config.font_size)
    center_x = config.width / 2
    center_y = config.height * subtitle_config.position_y
    bbox = draw.multiline_textbbox(
        (center_x, center_y),
        text,
        font=font,
        anchor="mm",
        align="center",
        spacing=subtitle_config.line_spacing,
        stroke_width=subtitle_config.outline,
    )
    left, top, right, bottom = bbox
    backdrop = Image.new("RGBA", image.size, (0, 0, 0, 0))
    backdrop_draw = ImageDraw.Draw(backdrop)
    backdrop_draw.rounded_rectangle(
        (
            left - subtitle_config.caption_background_padding_x,
            top - subtitle_config.caption_background_padding_y,
            right + subtitle_config.caption_background_padding_x,
            bottom + subtitle_config.caption_background_padding_y,
        ),
        radius=subtitle_config.caption_background_radius,
        fill=_color_with_alpha(subtitle_config.caption_background_color),
    )
    image.alpha_composite(backdrop.filter(ImageFilter.GaussianBlur(radius=12)))
    image.alpha_composite(backdrop)
    if subtitle_config.shadow > 0:
        shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_draw.multiline_text(
            (center_x + subtitle_config.shadow, center_y + subtitle_config.shadow),
            text,
            font=font,
            anchor="mm",
            align="center",
            spacing=subtitle_config.line_spacing,
            fill=_color_with_alpha(subtitle_config.shadow_color),
            stroke_width=subtitle_config.outline,
            stroke_fill=_color_with_alpha(subtitle_config.shadow_color),
        )
        image.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(radius=4)))
    draw.multiline_text(
        (center_x, center_y),
        text,
        font=font,
        anchor="mm",
        align="center",
        spacing=subtitle_config.line_spacing,
        fill=subtitle_config.inactive_text_color,
        stroke_width=subtitle_config.outline,
        stroke_fill=subtitle_config.stroke_color,
    )
    image.save(output_path)


def _ass_to_overlay_events(
    subtitles_path: Path,
    config: CompositionConfig,
    subtitle_config: SubtitleConfig,
    work_dir: Path,
) -> list[SubtitleOverlay]:
    overlays: list[SubtitleOverlay] = []
    dialogue_index = 0
    for raw_line in subtitles_path.read_text().splitlines():
        if not raw_line.startswith("Dialogue:"):
            continue
        parts = raw_line.split(",", 9)
        if len(parts) != 10:
            continue
        start = _format_drawtext_timestamp(parts[1])
        end = _format_drawtext_timestamp(parts[2])
        text = re.sub(r"\{[^}]+\}", "", parts[9]).replace("\\N", "\n").strip()
        if not text:
            continue
        image_path = work_dir / f"{subtitles_path.stem}-overlay-{dialogue_index:02d}.png"
        _render_subtitle_overlay(text, image_path, config, subtitle_config)
        overlays.append(SubtitleOverlay(start=start, end=end, image_path=image_path))
        dialogue_index += 1
    return overlays


class VideoComposer:
    def __init__(
        self,
        config: CompositionConfig,
        subtitle_config: SubtitleConfig,
        reddit_card_config: RedditCardConfig,
        work_dir: Path,
    ) -> None:
        self.config = config
        self.subtitle_config = subtitle_config
        self.reddit_card_config = reddit_card_config
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def render_reddit_post_card(self, candidate: ContentCandidate, output_path: Path) -> Path:
        card_title = normalize_spacing(sanitize_narration_text(candidate.title))
        card_body = normalize_spacing(sanitize_narration_text(candidate.body, drop_navigation_lines=True))
        canvas = Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        draw = ImageDraw.Draw(canvas)
        card_ratio = 1306 / 550
        card_width = self.reddit_card_config.card_width
        card_height = round(card_width / card_ratio)
        card_x = (self.config.width - card_width) // 2
        card_y = round((self.config.height * self.reddit_card_config.position_y) - (card_height / 2))
        card_bounds = (card_x, card_y, card_x + card_width, card_y + card_height)
        shadow_draw.rounded_rectangle(
            (
                card_x + 12,
                card_y + 18,
                card_x + card_width + 12,
                card_y + card_height + 18,
            ),
            radius=self.reddit_card_config.corner_radius,
            fill=(0, 0, 0, 150),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(radius=18)))
        draw.rounded_rectangle(
            card_bounds,
            radius=self.reddit_card_config.corner_radius,
            fill=self.reddit_card_config.background_color,
            outline=self.reddit_card_config.border_color,
            width=2,
        )

        meta_font = self._card_font(self.reddit_card_config.meta_font_size)
        title_font = self._card_font(self.reddit_card_config.title_font_size)
        body_font = self._card_font(self.reddit_card_config.body_font_size)

        icon_size = 28
        content_padding_x = 34
        icon_x = card_x + content_padding_x
        icon_y = card_y + 30
        draw.ellipse(
            (icon_x, icon_y, icon_x + icon_size, icon_y + icon_size),
            fill=self.reddit_card_config.accent_color,
        )
        relative_age = self._relative_post_age(candidate.created_utc)
        meta_text = f"r/{candidate.subreddit}  {relative_age}"
        draw.text(
            (icon_x + icon_size + 16, card_y + 28),
            meta_text,
            font=meta_font,
            fill=self.reddit_card_config.meta_color,
        )

        title_width = card_width - (content_padding_x * 2)
        title_lines = self._wrap_card_text(card_title, title_font, title_width, max_lines=2)
        title_text = "\n".join(title_lines)
        title_top = card_y + 84
        draw.multiline_text(
            (card_x + content_padding_x, title_top),
            title_text,
            font=title_font,
            fill="white",
            spacing=8,
        )
        title_bbox = draw.multiline_textbbox(
            (card_x + content_padding_x, title_top),
            title_text,
            font=title_font,
            spacing=8,
        )
        footer_text = f"{self._format_count(candidate.score)} upvotes    {self._format_count(candidate.num_comments)} comments"
        footer_y = card_y + card_height - 54
        body_top = title_bbox[3] + 18
        body_bottom = footer_y - 24
        body_lines = self._fit_card_lines(
            card_body,
            body_font,
            title_width,
            max_height=max(int(body_bottom - body_top), 0),
            max_lines=self.reddit_card_config.max_body_lines,
            spacing=9,
        )
        body_text = "\n".join(body_lines)
        if body_text:
            draw.multiline_text(
                (card_x + content_padding_x, body_top),
                body_text,
                font=body_font,
                fill=self.reddit_card_config.meta_color,
                spacing=9,
            )
        draw.text(
            (card_x + content_padding_x, footer_y),
            footer_text,
            font=meta_font,
            fill=self.reddit_card_config.secondary_color,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path)
        return output_path

    def _card_font(self, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return _subtitle_font(self.config, font_size)

    def render_title_card(self, text: str, duration: float, output_path: Path) -> Path:
        text_file = output_path.with_suffix(".txt")
        atomic_write_text(text_file, textwrap.fill(text, width=22))
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x111827:s={self.config.width}x{self.config.height // 2}:d={duration}",
                "-vf",
                f"drawtext=fontfile={self.config.font_file}:textfile={text_file}:fontcolor=white:fontsize=54:line_spacing=14:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.35:boxborderw=30",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        return output_path

    def extract_clip(self, source_path: Path, start: float, end: float, output_path: Path) -> Path:
        duration = max(end - start, 1)
        run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start}",
                "-t",
                f"{duration}",
                "-i",
                str(source_path),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        return output_path

    def _build_looped_gameplay(self, gameplay_path: Path, audio_path: Path) -> Path:
        """Create a gameplay video long enough to cover the audio duration.

        Uses the concat demuxer to repeat the clip instead of ``-stream_loop -1``
        which produces corrupt NAL units at loop boundaries.  If probing fails
        (e.g. files don't exist yet during tests) the original path is returned
        unchanged so the compose command still receives a valid ``-i`` argument.
        """
        import json
        import math
        import subprocess

        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(audio_path),
                ],
                capture_output=True,
                text=True,
            )
            audio_duration = float(json.loads(probe.stdout)["format"]["duration"])

            probe_gp = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(gameplay_path),
                ],
                capture_output=True,
                text=True,
            )
            clip_duration = float(json.loads(probe_gp.stdout)["format"]["duration"])
        except (KeyError, ValueError, FileNotFoundError, json.JSONDecodeError):
            # Probing failed – fall back to the raw path (tests / missing files).
            return gameplay_path

        # Add 10s safety margin so we never run short
        loops_needed = math.ceil((audio_duration + 10) / clip_duration)
        if loops_needed <= 1:
            return gameplay_path

        concat_path = self.work_dir / f"{gameplay_path.stem}-loop.txt"
        escaped = self._escape_concat_path(gameplay_path)
        lines = [f"file '{escaped}'\n" for _ in range(loops_needed)]
        from ..utils.files import atomic_write_text as _awt

        _awt(concat_path, "".join(lines))

        looped_path = self.work_dir / f"{gameplay_path.stem}-looped.mp4"
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                "-an",
                str(looped_path),
            ]
        )
        return looped_path

    def compose_story_gameplay(
        self,
        *,
        gameplay_path: Path,
        subtitles_path: Path,
        audio_path: Path,
        intro_card_path: Path | None,
        output_path: Path,
    ) -> Path:
        overlay_track_path = self._build_story_overlay_track(subtitles_path)
        target_fps = self.config.target_fps
        transition_sfx_path = self._story_card_transition_sfx_path() if intro_card_path is not None else None
        audio_map = "1:a"
        # V4: Removed zoompan (caused video freeze after ~6s due to internal frame
        # counter exhaustion on loop boundaries) and setpts speed-up (gameplay clips
        # are now pre-accelerated during clip mining).
        # V4.1: Replaced -stream_loop -1 with concat-demuxer loop to avoid corrupt
        # NAL units at H.264 loop boundaries.
        looped_gameplay_path = self._build_looped_gameplay(gameplay_path, audio_path)
        filter_steps = [
            (
                f"[0:v]scale={self.config.width}:{self.config.height}:force_original_aspect_ratio=increase,"
                f"crop={self.config.width}:{self.config.height},fps={target_fps}[story0]"
            )
        ]
        current_label = "story0"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(looped_gameplay_path),
            "-i",
            str(audio_path),
        ]
        next_input_index = 2
        if overlay_track_path is not None:
            command.extend(["-i", str(overlay_track_path)])
            filter_steps.append(
                f"[{current_label}][{next_input_index}:v]overlay=0:0:shortest=0:repeatlast=0:eof_action=pass:alpha=straight[story1]"
            )
            current_label = "story1"
            next_input_index += 1

        if intro_card_path is not None:
            intro_card_index = next_input_index
            command.extend(["-loop", "1", "-i", str(intro_card_path)])
            next_input_index += 1
            intro_fade_duration = min(
                self.reddit_card_config.intro_animation_seconds,
                self.reddit_card_config.duration_seconds,
            )
            outro_fade_duration = min(
                self.reddit_card_config.outro_animation_seconds,
                self.reddit_card_config.duration_seconds,
            )
            fade_start = max(self.reddit_card_config.duration_seconds - outro_fade_duration, 0.0)
            filter_steps.append(
                f"[{intro_card_index}:v]format=rgba,"
                f"fade=in:st=0:d={intro_fade_duration:.2f}:alpha=1,"
                f"fade=out:st={fade_start:.2f}:d={outro_fade_duration:.2f}:alpha=1[card_faded]"
            )
            filter_steps.append(
                f"[{current_label}][card_faded]overlay=0:0:"
                f"enable='between(t,0,{self.reddit_card_config.duration_seconds:.2f})'[v]"
            )
            if transition_sfx_path is not None:
                transition_sfx_index = next_input_index
                command.extend(["-i", str(transition_sfx_path)])
                next_input_index += 1
                fade_start_ms = round(fade_start * 1000)
                filter_steps.append(
                    f"[{transition_sfx_index}:a]aformat=channel_layouts=stereo,asplit=2[sfx_intro_src][sfx_outro_src]"
                )
                filter_steps.append(
                    f"[sfx_intro_src]volume={self.reddit_card_config.transition_sfx_volume:.2f},adelay=0|0[sfx_intro]"
                )
                filter_steps.append(
                    f"[sfx_outro_src]volume={self.reddit_card_config.transition_sfx_volume:.2f},adelay={fade_start_ms}|{fade_start_ms}[sfx_outro]"
                )
                filter_steps.append("[1:a]aformat=channel_layouts=stereo[story_audio]")
                filter_steps.append(
                    "[story_audio][sfx_intro][sfx_outro]"
                    "amix=inputs=3:normalize=0:dropout_transition=0,"
                    "alimiter=limit=0.95[a]"
                )
                audio_map = "[a]"
        else:
            filter_steps.append(f"[{current_label}]null[v]")
        filter_complex = ";".join(filter_steps)
        command.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                audio_map,
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-r",
                str(target_fps),
                "-movflags",
                "+faststart",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        run_command(command)
        return output_path

    def _story_card_transition_sfx_path(self) -> Path | None:
        raw_path = (self.reddit_card_config.transition_sfx_path or "").strip()
        if not raw_path:
            return None
        candidate = Path(raw_path).expanduser()
        if candidate.exists():
            return candidate
        return None

    def _build_story_overlay_track(self, subtitles_path: Path) -> Path | None:
        overlays = self._load_story_overlays(subtitles_path)
        if not overlays:
            return None
        blank_path = self.work_dir / f"{subtitles_path.stem}-overlay-blank.png"
        if not blank_path.exists():
            Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0)).save(blank_path)
        timeline: list[tuple[Path, float]] = []
        cursor = 0.0
        for overlay in overlays:
            if overlay.start > cursor:
                timeline.append((blank_path, overlay.start - cursor))
            duration = max(overlay.end - overlay.start, 0.03)
            timeline.append((overlay.image_path, duration))
            cursor = max(cursor, overlay.end)
        if not timeline:
            return None
        concat_path = self.work_dir / f"{subtitles_path.stem}-overlay-track.txt"
        concat_lines: list[str] = []
        for path, duration in timeline:
            concat_lines.append(f"file '{self._escape_concat_path(path)}'\n")
            concat_lines.append(f"duration {duration:.3f}\n")
        # Repeat the last frame entry so the concat demuxer preserves the final visible state.
        concat_lines.append(f"file '{self._escape_concat_path(timeline[-1][0])}'\n")
        atomic_write_text(concat_path, "".join(concat_lines))
        overlay_track_path = self.work_dir / f"{subtitles_path.stem}-overlay-track.mov"
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-vf",
                f"fps={self.config.target_fps},format=argb",
                "-an",
                "-c:v",
                "qtrle",
                "-pix_fmt",
                "argb",
                str(overlay_track_path),
            ]
        )
        return overlay_track_path

    def _load_story_overlays(self, subtitles_path: Path) -> list[SubtitleOverlay]:
        kinetic_manifest_path = subtitles_path.with_suffix(".kinetic.json")
        if kinetic_manifest_path.exists():
            return self._kinetic_to_overlay_events(kinetic_manifest_path)
        return _ass_to_overlay_events(subtitles_path, self.config, self.subtitle_config, self.work_dir)

    def _kinetic_to_overlay_events(self, manifest_path: Path) -> list[SubtitleOverlay]:
        payload = load_json(manifest_path, default={})
        payload_format = str(payload.get("format", "kinetic_subtitles_v1"))
        segments = [TranscriptSegment.model_validate(item) for item in payload.get("segments", [])]
        overlays: list[SubtitleOverlay] = []
        event_index = 0
        for segment_index, segment in enumerate(segments):
            if not segment.words:
                continue
            display_end = segment.end
            if payload_format == "kinetic_subtitles_v1" and segment_index + 1 < len(segments):
                display_end = segments[segment_index + 1].start
            for word_index, word in enumerate(segment.words):
                state_end = word.end
                if word_index == len(segment.words) - 1:
                    state_end = max(display_end, word.end)
                pop_duration_seconds = self.subtitle_config.pop_animation_ms / 1000
                pop_end = min(state_end, word.start + pop_duration_seconds) if pop_duration_seconds > 0 else word.start
                if pop_duration_seconds > 0 and pop_end > word.start:
                    image_path = self.work_dir / f"{manifest_path.stem}-kinetic-{event_index:03d}.png"
                    self._render_kinetic_overlay(
                        segment,
                        active_word_index=word_index,
                        output_path=image_path,
                        scale=self.subtitle_config.active_word_scale + self.subtitle_config.pop_animation_strength,
                        use_windowed_rows=payload_format == "kinetic_subtitles_v1",
                    )
                    overlays.append(SubtitleOverlay(start=word.start, end=pop_end, image_path=image_path))
                    event_index += 1
                steady_start = pop_end if pop_end > word.start else word.start
                if state_end > steady_start:
                    image_path = self.work_dir / f"{manifest_path.stem}-kinetic-{event_index:03d}.png"
                    self._render_kinetic_overlay(
                        segment,
                        active_word_index=word_index,
                        output_path=image_path,
                        scale=self.subtitle_config.active_word_scale,
                        use_windowed_rows=payload_format == "kinetic_subtitles_v1",
                    )
                    overlays.append(SubtitleOverlay(start=steady_start, end=state_end, image_path=image_path))
                    event_index += 1
        return overlays

    def _render_kinetic_overlay(
        self,
        segment: TranscriptSegment,
        *,
        active_word_index: int,
        output_path: Path,
        scale: float,
        use_windowed_rows: bool = False,
    ) -> None:
        image = Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        base_font = _subtitle_font(self.config, self.subtitle_config.font_size)
        active_font = _subtitle_font(self.config, max(round(self.subtitle_config.font_size * scale), 1))
        max_scale = self.subtitle_config.active_word_scale + self.subtitle_config.pop_animation_strength
        max_active_font = _subtitle_font(self.config, max(round(self.subtitle_config.font_size * max_scale), 1))
        rows = self._caption_rows(segment, active_word_index=active_word_index, use_windowed_rows=use_windowed_rows)
        if not rows:
            image.save(output_path)
            return
        row_layouts = self._build_kinetic_rows(draw, segment, rows, base_font, max_active_font)
        block_width = max((row.width for row in row_layouts), default=0.0)
        block_height = sum(row.height for row in row_layouts)
        block_height += self.subtitle_config.line_spacing * max(len(row_layouts) - 1, 0)
        block_top = round((self.config.height * self.subtitle_config.position_y) - (block_height / 2))
        self._draw_caption_backdrop(image, block_width, block_height, block_top)

        row_top = float(block_top)
        for row_layout in row_layouts:
            row_center_y = row_top + (row_layout.height / 2)
            x_cursor = (self.config.width - row_layout.width) / 2
            for word_slot in row_layout.words:
                slot_center_x = x_cursor + (word_slot.slot_width / 2)
                is_active = word_slot.word_index == active_word_index
                self._draw_kinetic_word(
                    draw,
                    image,
                    word_slot.text,
                    center_x=slot_center_x,
                    center_y=row_center_y,
                    font=active_font if is_active else base_font,
                    fill=self.subtitle_config.highlight_color if is_active else self.subtitle_config.inactive_text_color,
                )
                x_cursor += word_slot.slot_width + self.subtitle_config.word_spacing
            row_top += row_layout.height + self.subtitle_config.line_spacing
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)

    def _caption_rows(
        self,
        segment: TranscriptSegment,
        *,
        active_word_index: int,
        use_windowed_rows: bool,
    ) -> list[list[int]]:
        if not segment.words:
            return []
        rows = build_caption_rows([word.text for word in segment.words], self.subtitle_config)
        if use_windowed_rows or len(rows) > self.subtitle_config.max_lines_per_caption:
            return self._wrap_segment_words(segment, active_word_index=active_word_index)
        return rows

    def _build_kinetic_rows(
        self,
        draw: ImageDraw.ImageDraw,
        segment: TranscriptSegment,
        rows: list[list[int]],
        base_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_active_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> list[KineticRowLayout]:
        layouts: list[KineticRowLayout] = []
        for row in rows:
            word_slots: list[KineticWordSlot] = []
            row_height = 0.0
            row_width = 0.0
            for position, word_index in enumerate(row):
                word_text = segment.words[word_index].text
                base_width, base_height = self._measure_text_box(draw, word_text, base_font)
                active_width, active_height = self._measure_text_box(draw, word_text, max_active_font)
                # Use the base size plus half the growth as slot size.  This keeps
                # words close together while leaving enough room for the active
                # word to scale up without clipping its neighbours noticeably.
                slot_width = base_width + (active_width - base_width) * 0.5
                slot_height = base_height + (active_height - base_height) * 0.5
                word_slots.append(
                    KineticWordSlot(
                        word_index=word_index,
                        text=word_text,
                        slot_width=slot_width,
                        slot_height=slot_height,
                    )
                )
                row_height = max(row_height, slot_height)
                row_width += slot_width
                if position < len(row) - 1:
                    row_width += self.subtitle_config.word_spacing
            layouts.append(KineticRowLayout(words=word_slots, width=row_width, height=row_height))
        return layouts

    def _wrap_segment_words(self, segment: TranscriptSegment, *, active_word_index: int | None = None) -> list[list[int]]:
        if not segment.words:
            return []
        max_visible_words = max(
            self.subtitle_config.max_words_per_line * self.subtitle_config.max_lines_per_caption,
            1,
        )
        total_words = len(segment.words)
        start_index = 0
        if active_word_index is not None and total_words > max_visible_words:
            clamped_index = min(max(active_word_index, 0), total_words - 1)
            target_slot = max_visible_words // 2
            start_index = min(max(clamped_index - target_slot, 0), total_words - max_visible_words)
        visible_indices = list(range(start_index, min(start_index + max_visible_words, total_words)))
        return [
            visible_indices[index : index + self.subtitle_config.max_words_per_line]
            for index in range(0, len(visible_indices), self.subtitle_config.max_words_per_line)
        ]

    def _draw_caption_backdrop(self, image: Image.Image, block_width: float, block_height: float, block_top: float) -> None:
        if block_width <= 0 or block_height <= 0:
            return
        left = (self.config.width - block_width) / 2
        backdrop = Image.new("RGBA", image.size, (0, 0, 0, 0))
        backdrop_draw = ImageDraw.Draw(backdrop)
        backdrop_draw.rounded_rectangle(
            (
                left - self.subtitle_config.caption_background_padding_x,
                block_top - self.subtitle_config.caption_background_padding_y,
                left + block_width + self.subtitle_config.caption_background_padding_x,
                block_top + block_height + self.subtitle_config.caption_background_padding_y,
            ),
            radius=self.subtitle_config.caption_background_radius,
            fill=_color_with_alpha(self.subtitle_config.caption_background_color),
        )
        image.alpha_composite(backdrop.filter(ImageFilter.GaussianBlur(radius=14)))
        image.alpha_composite(backdrop)

    def _draw_kinetic_word(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        text: str,
        *,
        center_x: float,
        center_y: float,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        fill: str,
    ) -> None:
        if self.subtitle_config.shadow > 0:
            shadow_layer = Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            shadow_draw.text(
                (center_x + self.subtitle_config.shadow, center_y + self.subtitle_config.shadow),
                text,
                font=font,
                anchor="mm",
                fill=_color_with_alpha(self.subtitle_config.shadow_color),
                stroke_width=self.subtitle_config.outline,
                stroke_fill=_color_with_alpha(self.subtitle_config.shadow_color),
            )
            image.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(radius=4)))
        draw.text(
            (center_x, center_y),
            text,
            font=font,
            anchor="mm",
            fill=fill,
            stroke_width=self.subtitle_config.outline,
            stroke_fill=self.subtitle_config.stroke_color,
        )

    def _measure_text_box(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> tuple[float, float]:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=self.subtitle_config.outline)
        return (right - left, bottom - top)

    def _escape_concat_path(self, path: Path) -> str:
        return path.as_posix().replace("'", r"'\''")

    def _relative_post_age(self, created_utc: int) -> str:
        now_utc = int(datetime.now(UTC).timestamp())
        age_hours = max((now_utc - created_utc) // 3600, 1)
        if age_hours < 24:
            return f"{age_hours} hr ago"
        age_days = max(age_hours // 24, 1)
        return f"{age_days} d ago"

    def _format_count(self, value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}k"
        return str(value)

    def _measure_multiline_height(
        self,
        lines: list[str],
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        *,
        spacing: int,
    ) -> int:
        if not lines:
            return 0
        text = "\n".join(lines)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        bbox = measure.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
        return int(bbox[3] - bbox[1])

    def _fit_card_lines(
        self,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
        *,
        max_height: int,
        max_lines: int,
        spacing: int,
    ) -> list[str]:
        lines = self._wrap_card_text(text, font, max_width, max_lines=max_lines)
        if not lines or max_height <= 0:
            return []
        fitted = list(lines)
        while fitted and self._measure_multiline_height(fitted, font, spacing=spacing) > max_height:
            fitted = fitted[:-1]
            if fitted:
                fitted[-1] = self._ellipsize_line(fitted[-1])
        if not fitted:
            return []
        if len(fitted) < len(lines):
            fitted[-1] = self._ellipsize_line(fitted[-1])
        return fitted

    def _ellipsize_line(self, value: str) -> str:
        base = value.rstrip(". ")
        if base.endswith("..."):
            base = base[:-3].rstrip(". ")
        if not base:
            return "..."
        return f"{base}..."

    def _wrap_card_text(
        self,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
        *,
        max_lines: int,
    ) -> list[str]:
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        words = text.split()
        lines: list[str] = []
        current_line = ""
        for word in words:
            candidate = word if not current_line else f"{current_line} {word}"
            if measure.textlength(candidate, font=font) <= max_width:
                current_line = candidate
                continue
            if current_line:
                lines.append(current_line)
            current_line = word
            if len(lines) == max_lines:
                break
        if current_line and len(lines) < max_lines:
            lines.append(current_line)
        if len(lines) == max_lines and len(" ".join(lines).split()) < len(words):
            lines[-1] = self._ellipsize_line(lines[-1])
        return lines

    def compose_longform_clip(
        self,
        *,
        clip_path: Path,
        subtitles_path: Path,
        output_path: Path,
    ) -> Path:
        target_fps = self.config.target_fps
        filter_complex = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"fps={target_fps},"
            f"subtitles={subtitles_path}:force_style='{_subtitle_style(self.config)}'[v]"
        )
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(clip_path),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-r",
                str(target_fps),
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        return output_path

    def compose_hybrid(
        self,
        *,
        clip_path: Path,
        gameplay_path: Path,
        subtitles_path: Path,
        output_path: Path,
    ) -> Path:
        target_fps = self.config.target_fps
        # V4: Removed setpts speed-up — gameplay clips are pre-accelerated during mining.
        # V4.1: Replaced -stream_loop -1 with concat-demuxer loop.
        looped_gameplay_path = self._build_looped_gameplay(gameplay_path, clip_path)
        filter_complex = (
            "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[top];"
            "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bottom];"
            f"[top][bottom]vstack=inputs=2,fps={target_fps}[stack];"
            f"[stack]subtitles={subtitles_path}:force_style='{_subtitle_style(self.config)}'[v]"
        )
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(clip_path),
                "-i",
                str(looped_gameplay_path),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-r",
                str(target_fps),
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        return output_path
