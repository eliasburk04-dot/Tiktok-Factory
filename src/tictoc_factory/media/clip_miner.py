from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import ClipCandidate, TranscriptSegment
from ..utils.process import probe_duration, run_command
from ..utils.text import summarize_text

EMOTION_TERMS = {"shocking", "crazy", "wild", "exploded", "fire", "viral", "laughed", "controversy"}
CONFLICT_TERMS = {"but", "however", "wrong", "kill", "fired", "disaster", "problem", "returned"}
QUESTION_TERMS = {"why", "how", "would", "what", "when", "?"}


class ClipMiner:
    def __init__(self, target_lengths: list[int]) -> None:
        self.target_lengths = target_lengths

    def load_sidecar_segments(self, media_path: Path) -> list[TranscriptSegment]:
        json_path = media_path.with_suffix(".segments.json")
        if json_path.exists():
            payload = json.loads(json_path.read_text())
            return [TranscriptSegment.model_validate(item) for item in payload]
        return []

    def detect_silence(self, media_path: Path) -> list[tuple[float, float]]:
        try:
            result = run_command(
                [
                    "ffmpeg",
                    "-i",
                    str(media_path),
                    "-af",
                    "silencedetect=noise=-28dB:d=0.4",
                    "-f",
                    "null",
                    "-",
                ]
            )
            output = result.stderr
        except Exception:
            return []
        starts = [float(match.group(1)) for match in re.finditer(r"silence_start: ([0-9.]+)", output)]
        ends = [float(match.group(1)) for match in re.finditer(r"silence_end: ([0-9.]+)", output)]
        return list(zip(starts, ends, strict=False))

    def rank_segments(
        self,
        *,
        media_path: Path,
        transcript_segments: list[TranscriptSegment],
        silence_intervals: list[tuple[float, float]] | None = None,
        top_k: int = 5,
    ) -> list[ClipCandidate]:
        if transcript_segments:
            ranked = self._rank_transcript_windows(transcript_segments, silence_intervals or [])
            for item in ranked:
                item.source_path = media_path
            return ranked[:top_k]
        return self._rank_audio_only(media_path, silence_intervals or [])[:top_k]

    def _rank_transcript_windows(
        self,
        transcript_segments: list[TranscriptSegment],
        silence_intervals: list[tuple[float, float]],
    ) -> list[ClipCandidate]:
        ranked: list[ClipCandidate] = []
        for start_index in range(len(transcript_segments)):
            for target_length in self.target_lengths:
                collected: list[TranscriptSegment] = []
                for segment in transcript_segments[start_index:]:
                    collected.append(segment)
                    duration = collected[-1].end - collected[0].start
                    if duration > max(self.target_lengths) and len(collected) > 1:
                        collected.pop()
                        break
                    if duration >= target_length or duration >= max(self.target_lengths):
                        break
                if not collected:
                    continue
                text = " ".join(item.text for item in collected)
                words = text.lower().split()
                emotion_hits = sum(1 for token in words if token.strip(".,!?") in EMOTION_TERMS)
                conflict_hits = sum(1 for token in words if token.strip(".,!?") in CONFLICT_TERMS)
                question_hits = sum(1 for token in words if token.strip(".,!?") in QUESTION_TERMS)
                pace = min(len(words) / max(collected[-1].end - collected[0].start, 1.0), 5.0)
                silence_hits = sum(
                    1
                    for start, end in silence_intervals
                    if collected[0].start - 1 <= start <= collected[-1].end + 1
                    or collected[0].start - 1 <= end <= collected[-1].end + 1
                )
                score = (
                    emotion_hits * 1.6
                    + conflict_hits * 1.7
                    + question_hits * 1.4
                    + pace
                    + silence_hits * 0.6
                )
                ranked.append(
                    ClipCandidate(
                        start=collected[0].start,
                        end=collected[-1].end,
                        score=round(score, 2),
                        summary=summarize_text(text, word_limit=20),
                        transcript_excerpt=text,
                        reasons=[
                            f"emotion_hits={emotion_hits}",
                            f"conflict_hits={conflict_hits}",
                            f"question_hits={question_hits}",
                            f"pace={pace:.2f}",
                            f"silence_hits={silence_hits}",
                        ],
                    )
                )
        unique: dict[tuple[float, float], ClipCandidate] = {}
        for item in ranked:
            key = (item.start, item.end)
            current = unique.get(key)
            if current is None or item.score > current.score:
                unique[key] = item
        return sorted(unique.values(), key=lambda item: (item.score, -(item.end - item.start)), reverse=True)

    def _rank_audio_only(
        self,
        media_path: Path,
        silence_intervals: list[tuple[float, float]],
    ) -> list[ClipCandidate]:
        duration = probe_duration(media_path)
        if not silence_intervals:
            silence_intervals = [(0.0, 0.0), (duration, duration)]
        ranked: list[ClipCandidate] = []
        for target_length in self.target_lengths:
            start = 0.0
            while start + target_length <= duration:
                end = start + target_length
                silence_hits = sum(1 for left, right in silence_intervals if start <= left <= end or start <= right <= end)
                ranked.append(
                    ClipCandidate(
                        start=start,
                        end=end,
                        score=1.0 + silence_hits * 0.5,
                        summary=f"Audio-only candidate {int(start)}s to {int(end)}s",
                        transcript_excerpt="",
                        reasons=[f"silence_hits={silence_hits}"],
                        source_path=media_path,
                    )
                )
                start += target_length / 2
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked
