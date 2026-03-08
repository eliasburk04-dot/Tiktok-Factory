from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..models import CompositionConfig, ContentCandidate, RedditCardConfig, SubtitleConfig, TranscriptSegment
from ..utils.files import atomic_write_text, load_json
from ..utils.process import run_command


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


def _render_subtitle_overlay(
    text: str,
    output_path: Path,
    config: CompositionConfig,
    subtitle_config: SubtitleConfig,
) -> None:
    image = Image.new("RGBA", (config.width, config.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _subtitle_font(config, font_size=subtitle_config.font_size)
    bbox = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        align="center",
        spacing=10,
        stroke_width=subtitle_config.outline,
    )
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x_position = (config.width - text_width) / 2
    y_position = (config.height * subtitle_config.position_y) - (text_height / 2)
    if subtitle_config.shadow > 0:
        draw.multiline_text(
            (x_position + subtitle_config.shadow, y_position + subtitle_config.shadow),
            text,
            font=font,
            align="center",
            spacing=10,
            fill=subtitle_config.shadow_color,
            stroke_width=0,
        )
    draw.multiline_text(
        (x_position, y_position),
        text,
        font=font,
        align="center",
        spacing=10,
        fill="white",
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
        title_lines = self._wrap_card_text(candidate.title, title_font, title_width, max_lines=2)
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
            candidate.body,
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
        # V4: Removed zoompan (caused video freeze after ~6s due to internal frame
        # counter exhaustion on loop boundaries) and setpts speed-up (gameplay clips
        # are now pre-accelerated during clip mining).
        filter_steps = [
            (
                f"[0:v]scale={self.config.width}:{self.config.height}:force_original_aspect_ratio=increase,"
                f"crop={self.config.width}:{self.config.height},fps=30[story0]"
            )
        ]
        current_label = "story0"
        command = [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(gameplay_path),
            "-i",
            str(audio_path),
        ]
        next_input_index = 2
        if overlay_track_path is not None:
            command.extend(["-i", str(overlay_track_path)])
            filter_steps.append(f"[{current_label}][{next_input_index}:v]overlay=0:0:shortest=1[story1]")
            current_label = "story1"
            next_input_index += 1

        if intro_card_path is not None:
            fade_start = max(self.reddit_card_config.duration_seconds - 0.4, 0.0)
            fade_duration = self.reddit_card_config.duration_seconds - fade_start
            filter_steps.append(
                f"[{next_input_index}:v]format=rgba,"
                f"fade=out:st={fade_start:.2f}:d={fade_duration:.2f}:alpha=1[card_faded]"
            )
            filter_steps.append(
                f"[{current_label}][card_faded]overlay=0:0:"
                f"enable='between(t,0,{self.reddit_card_config.duration_seconds:.2f})'[v]"
            )
        else:
            filter_steps.append(f"[{current_label}]null[v]")
        filter_complex = ";".join(filter_steps)
        if intro_card_path is not None:
            command.extend(["-loop", "1", "-i", str(intro_card_path)])
        command.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "1:a",
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-movflags",
                "+faststart",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        run_command(command)
        return output_path

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
                "fps=30,format=rgba",
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
        segments = [TranscriptSegment.model_validate(item) for item in payload.get("segments", [])]
        overlays: list[SubtitleOverlay] = []
        event_index = 0
        for segment_index, segment in enumerate(segments):
            if not segment.words:
                continue
            display_end = segments[segment_index + 1].start if segment_index + 1 < len(segments) else segment.end
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
    ) -> None:
        image = Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        base_font = _subtitle_font(self.config, self.subtitle_config.font_size)
        active_font = _subtitle_font(self.config, max(round(self.subtitle_config.font_size * scale), 1))
        rows = self._wrap_segment_words(segment)
        if not rows:
            image.save(output_path)
            return
        base_line_height = self._text_height(draw, "Ag", base_font)
        active_line_height = self._text_height(draw, "Ag", active_font)
        row_height = max(base_line_height, active_line_height)
        row_spacing = 18
        block_height = (row_height * len(rows)) + (row_spacing * max(len(rows) - 1, 0))
        block_top = round((self.config.height * self.subtitle_config.position_y) - (block_height / 2))
        space_width = self._space_width(draw, base_font)
        for line_index, line_words in enumerate(rows):
            row_top = float(block_top + (line_index * (row_height + row_spacing)))
            row_center_y = row_top + (row_height / 2)
            row_width = sum(draw.textlength(segment.words[word].text, font=base_font) for word in line_words)
            row_width += space_width * max(len(line_words) - 1, 0)
            x_cursor = (self.config.width - row_width) / 2
            for word in line_words:
                word_text = segment.words[word].text
                base_width = draw.textlength(word_text, font=base_font)
                is_active = word == active_word_index
                if is_active:
                    self._draw_kinetic_word(
                        draw,
                        word_text,
                        x_cursor,
                        row_center_y=row_center_y,
                        base_width=base_width,
                        font=active_font,
                        fill=self.subtitle_config.highlight_color,
                        image=image,
                        is_active=True,
                    )
                else:
                    self._draw_kinetic_word(
                        draw,
                        word_text,
                        x_cursor,
                        row_center_y=row_center_y,
                        base_width=base_width,
                        font=base_font,
                        fill="white",
                    )
                x_cursor += base_width + space_width
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)

    def _wrap_segment_words(self, segment: TranscriptSegment) -> list[list[int]]:
        rows: list[list[int]] = []
        current_row: list[int] = []
        for index, _word in enumerate(segment.words):
            if len(rows) >= self.subtitle_config.max_lines_per_caption:
                break
            current_row.append(index)
            if len(current_row) == self.subtitle_config.max_words_per_line:
                rows.append(current_row)
                current_row = []
        if current_row and len(rows) < self.subtitle_config.max_lines_per_caption:
            rows.append(current_row)
        return rows

    def _draw_kinetic_word(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        x_position: float,
        *,
        row_center_y: float,
        base_width: float,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        fill: str,
        image: Image.Image | None = None,
        is_active: bool = False,
    ) -> None:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=self.subtitle_config.outline)
        word_width = bbox[2] - bbox[0]
        word_height = bbox[3] - bbox[1]
        draw_x = x_position + ((base_width - word_width) / 2)
        draw_y = row_center_y - (word_height / 2)
        if is_active and image is not None:
            glow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow_layer)
            glow_draw.text(
                (draw_x, draw_y),
                text,
                font=font,
                fill=self.subtitle_config.highlight_color + "66",
                stroke_width=self.subtitle_config.outline + 6,
                stroke_fill=self.subtitle_config.highlight_color + "33",
            )
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=8))
            image.alpha_composite(glow_layer)
        if self.subtitle_config.shadow > 0:
            draw.text(
                (draw_x + self.subtitle_config.shadow, draw_y + self.subtitle_config.shadow),
                text,
                font=font,
                fill=self.subtitle_config.shadow_color,
                stroke_width=0,
            )
        draw.text(
            (draw_x, draw_y),
            text,
            font=font,
            fill=fill,
            stroke_width=self.subtitle_config.outline,
            stroke_fill=self.subtitle_config.stroke_color,
        )

    def _text_height(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> int:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=self.subtitle_config.outline)
        return int(bbox[3] - bbox[1])

    def _space_width(
        self, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    ) -> float:
        width = draw.textlength(" ", font=font)
        # Prevent very narrow fonts, or heavy scaled fonts from causing overlap
        return max(width, int(getattr(font, "size", 10) * 0.45))

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
        filter_complex = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
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
        # V4: Removed setpts speed-up — gameplay clips are pre-accelerated during mining.
        filter_complex = (
            "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[top];"
            "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bottom];"
            "[top][bottom]vstack=inputs=2[stack];"
            f"[stack]subtitles={subtitles_path}:force_style='{_subtitle_style(self.config)}'[v]"
        )
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(clip_path),
                "-stream_loop",
                "-1",
                "-i",
                str(gameplay_path),
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
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        return output_path
