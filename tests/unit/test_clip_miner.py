from __future__ import annotations

from pathlib import Path

from tictoc_factory.media.clip_miner import ClipMiner
from tictoc_factory.models import TranscriptSegment


def test_clip_miner_prioritizes_conflict_question_segments(
    podcast_segments: list[dict[str, object]],
) -> None:
    miner = ClipMiner(target_lengths=[25, 35, 45])
    segments = [TranscriptSegment.model_validate(item) for item in podcast_segments]

    ranked = miner.rank_segments(
        media_path=Path("/tmp/example.mp4"),
        transcript_segments=segments,
        silence_intervals=[(6.5, 7.0), (27.5, 28.0)],
        top_k=3,
    )

    assert ranked
    assert ranked[0].score > ranked[-1].score
    assert ranked[0].end - ranked[0].start <= 45
    assert "invest" in ranked[0].summary.lower() or "exploded" in ranked[0].summary.lower()
