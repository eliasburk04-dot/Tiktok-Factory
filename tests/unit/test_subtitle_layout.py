from __future__ import annotations

from tictoc_factory.models import SubtitleConfig, TranscriptSegment, WordTiming
from tictoc_factory.subtitles.layout import build_caption_rows, split_caption_segments


def _word(start: float, end: float, text: str) -> WordTiming:
    return WordTiming(start=start, end=end, text=text)


def test_build_caption_rows_rebalances_single_word_orphan() -> None:
    config = SubtitleConfig(
        max_words_per_line=3,
        max_lines_per_caption=2,
        max_chars_per_line=16,
    )

    rows = build_caption_rows(["Then", "the", "whisper", "said"], config)
    tokens = ["Then", "the", "whisper", "said"]

    assert [[tokens[index] for index in row] for row in rows] == [
        ["Then", "the"],
        ["whisper", "said"],
    ]


def test_build_caption_rows_balances_visual_weight_across_two_lines() -> None:
    config = SubtitleConfig(
        max_words_per_line=3,
        max_lines_per_caption=2,
        max_chars_per_line=18,
    )

    rows = build_caption_rows(["My", "roommate", "had", "a", "rule"], config)
    tokens = ["My", "roommate", "had", "a", "rule"]

    assert [[tokens[index] for index in row] for row in rows] == [
        ["My", "roommate"],
        ["had", "a", "rule"],
    ]


def test_build_caption_rows_preserves_sentence_boundary_when_balancing() -> None:
    config = SubtitleConfig(
        max_words_per_line=3,
        max_lines_per_caption=2,
        max_chars_per_line=18,
    )

    rows = build_caption_rows(["Okay.", "we", "do", "it"], config)
    tokens = ["Okay.", "we", "do", "it"]

    assert [[tokens[index] for index in row] for row in rows] == [
        ["Okay."],
        ["we", "do", "it"],
    ]


def test_build_caption_rows_falls_back_when_single_token_exceeds_char_budget() -> None:
    config = SubtitleConfig(
        max_words_per_line=2,
        max_lines_per_caption=2,
        max_chars_per_line=10,
    )

    rows = build_caption_rows(["supercalifragilisticexpialidocious", "door"], config)
    tokens = ["supercalifragilisticexpialidocious", "door"]

    assert [[tokens[index] for index in row] for row in rows] == [
        ["supercalifragilisticexpialidocious"],
        ["door"],
    ]


def test_split_caption_segments_breaks_on_punctuation_pause_and_group_budget() -> None:
    config = SubtitleConfig(
        max_words_per_line=3,
        max_lines_per_caption=2,
        max_chars_per_line=16,
        target_words_per_caption=4,
        max_words_per_caption=5,
        pause_threshold_ms=180,
        caption_lead_in_ms=40,
        caption_linger_ms=110,
    )
    segment = TranscriptSegment(
        start=0.0,
        end=3.10,
        text="Never open the basement door. Then the whisper said my name.",
        words=[
            _word(0.00, 0.20, "Never"),
            _word(0.20, 0.45, "open"),
            _word(0.45, 0.65, "the"),
            _word(0.65, 1.00, "basement"),
            _word(1.00, 1.25, "door."),
            _word(1.48, 1.72, "Then"),
            _word(1.72, 1.88, "the"),
            _word(1.88, 2.25, "whisper"),
            _word(2.25, 2.55, "said"),
            _word(2.55, 2.75, "my"),
            _word(2.75, 3.10, "name."),
        ],
    )

    groups = split_caption_segments([segment], config)

    assert [group.text for group in groups] == [
        "Never open the basement door.",
        "Then the whisper said",
        "my name.",
    ]
    assert groups[0].end <= groups[1].start
    assert groups[0].end > 1.25
    assert all(len(build_caption_rows([word.text for word in group.words], config)) <= 2 for group in groups)
