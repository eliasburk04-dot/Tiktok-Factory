"""Split a long video into multiple parts of 70–120 seconds.

The splitter uses the word-level timings from the subtitle manifest to cut
at sentence boundaries so no word is split mid-sentence.  The algorithm
guarantees every part is at least *min_duration* seconds and at most
*max_duration* seconds.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from ..utils.process import probe_duration, run_command

logger = logging.getLogger(__name__)

# We detect sentence boundaries by looking for words that end with these.
_SENTENCE_ENDINGS = {".", "!", "?", '."', '!"', '?"', ".'", "!'", "?'"}


@dataclass(frozen=True)
class VideoPart:
    """Describes one part of a split video."""

    part_number: int
    total_parts: int
    start_seconds: float
    end_seconds: float
    output_path: Path


def plan_split_points(
    word_timings: list[dict],
    total_duration: float,
    *,
    min_duration: float = 70.0,
    max_duration: float = 120.0,
) -> list[float]:
    """Return a list of cut-points (in seconds) between parts.

    Each cut-point is placed at the end of a sentence whose timestamp falls
    between *min_duration* and *max_duration* within the current part.  If no
    sentence boundary exists in that window the closest word boundary after
    *min_duration* is used.

    A final part shorter than *min_duration* is merged back into the
    previous part (i.e. the last cut is removed).
    """
    if total_duration <= max_duration:
        return []  # fits in one video

    # Collect sentence-ending timestamps
    sentence_ends: list[float] = []
    for timing in word_timings:
        text = timing.get("text", "").strip()
        end = float(timing.get("end", 0))
        if any(text.endswith(ending) for ending in _SENTENCE_ENDINGS):
            sentence_ends.append(end)

    # Also use all word-end times as fallback cut points
    word_ends: list[float] = [float(t.get("end", 0)) for t in word_timings if float(t.get("end", 0)) > 0]

    cuts: list[float] = []
    part_start = 0.0

    while True:
        remaining = total_duration - part_start
        if remaining <= max_duration:
            break  # last part fits

        # Look for best sentence boundary in [min_duration, max_duration]
        window_start = part_start + min_duration
        window_end = part_start + max_duration
        best_cut = None

        for ts in sentence_ends:
            if window_start <= ts <= window_end:
                best_cut = ts  # pick the latest sentence end in the window

        if best_cut is None:
            # No sentence boundary — fall back to any word boundary >= min_duration
            for ts in word_ends:
                if ts >= window_start:
                    best_cut = ts
                    break

        if best_cut is None:
            # No word boundary either — hard cut at max_duration
            best_cut = window_end

        cuts.append(best_cut)
        part_start = best_cut

    # Guard: if the final part would be too short, merge it back
    if cuts:
        final_length = total_duration - cuts[-1]
        if final_length < min_duration:
            cuts.pop()

    return cuts


def split_video(
    video_path: Path,
    subtitle_manifest_path: Path | None,
    output_dir: Path,
    *,
    min_duration: float = 70.0,
    max_duration: float = 120.0,
    job_id: str = "",
) -> list[VideoPart]:
    """Split *video_path* into parts and return the list of parts.

    If the video is already within [min, max] duration, a single-element
    list with the original path is returned (no re-encode).
    """
    total = probe_duration(video_path)

    # ── Collect word timings from the kinetic manifest ──────────────────
    word_timings: list[dict] = []
    if subtitle_manifest_path and subtitle_manifest_path.exists():
        payload = json.loads(subtitle_manifest_path.read_text())
        for seg in payload.get("segments", []):
            for w in seg.get("words", []):
                word_timings.append(w)

    cuts = plan_split_points(
        word_timings,
        total,
        min_duration=min_duration,
        max_duration=max_duration,
    )

    if not cuts:
        # Video fits in one part — no split needed
        return [
            VideoPart(
                part_number=1,
                total_parts=1,
                start_seconds=0.0,
                end_seconds=total,
                output_path=video_path,
            )
        ]

    # ── Execute splits ──────────────────────────────────────────────────
    boundaries = [0.0, *cuts, total]
    total_parts = len(boundaries) - 1
    parts: list[VideoPart] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = job_id or video_path.stem

    for idx in range(total_parts):
        start = boundaries[idx]
        end = boundaries[idx + 1]
        part_num = idx + 1
        out_path = output_dir / f"{base_name}-part{part_num}.mp4"

        run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                str(video_path),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-pix_fmt",
                "yuv420p",
                str(out_path),
            ]
        )
        parts.append(
            VideoPart(
                part_number=part_num,
                total_parts=total_parts,
                start_seconds=start,
                end_seconds=end,
                output_path=out_path,
            )
        )
        logger.info(
            "Split part %d/%d: %.1fs–%.1fs → %s",
            part_num,
            total_parts,
            start,
            end,
            out_path.name,
        )

    return parts
