from __future__ import annotations

from collections.abc import Sequence

from ..models import SubtitleConfig, TranscriptSegment

_TERMINAL_PUNCTUATION = (".", "!", "?", "…")
_ROW_BREAK_PUNCTUATION = (*_TERMINAL_PUNCTUATION, ",", ";", ":")
_WEAK_BREAK_STARTS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "because",
    "but",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "with",
    "your",
}
_WEAK_BREAK_ENDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "from",
    "in",
    "into",
    "is",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "their",
    "to",
    "with",
    "your",
}


def build_caption_rows(tokens: Sequence[str], config: SubtitleConfig) -> list[list[int]]:
    visible_indices = [index for index, token in enumerate(tokens) if token.strip()]
    if not visible_indices:
        return []

    candidate_rows = _enumerate_caption_rows(tokens, visible_indices, config)
    if candidate_rows:
        return min(candidate_rows, key=lambda rows: _score_row_partition(tokens, rows))

    return _greedy_caption_rows(tokens, visible_indices, config)


def split_caption_segments(
    segments: Sequence[TranscriptSegment],
    config: SubtitleConfig,
) -> list[TranscriptSegment]:
    grouped_segments: list[TranscriptSegment] = []
    prior_end = 0.0

    for segment in segments:
        if not segment.words:
            grouped_segments.append(segment)
            prior_end = max(prior_end, segment.end)
            continue

        start_index = 0
        while start_index < len(segment.words):
            end_index = _choose_group_end(segment, start_index, config)
            group_words = list(segment.words[start_index:end_index])
            next_start = segment.words[end_index].start if end_index < len(segment.words) else segment.end
            lead_in = config.caption_lead_in_ms / 1000
            linger = config.caption_linger_ms / 1000
            start = max(segment.start, group_words[0].start - lead_in, prior_end)
            natural_end = group_words[-1].end + linger
            end = min(segment.end, next_start, natural_end)
            end = max(end, group_words[-1].end, start + 0.05)
            grouped_segments.append(
                TranscriptSegment(
                    start=start,
                    end=end,
                    text=" ".join(word.text for word in group_words),
                    words=group_words,
                )
            )
            prior_end = end
            start_index = end_index

    return grouped_segments


def _greedy_caption_rows(
    tokens: Sequence[str],
    visible_indices: Sequence[int],
    config: SubtitleConfig,
) -> list[list[int]]:
    rows: list[list[int]] = []
    current_row: list[int] = []
    current_chars = 0

    for index in visible_indices:
        cleaned = tokens[index].strip()
        token_length = len(cleaned)
        projected_chars = token_length if not current_row else current_chars + 1 + token_length
        if current_row and (
            len(current_row) >= config.max_words_per_line or projected_chars > config.max_chars_per_line
        ):
            rows.append(current_row)
            current_row = [index]
            current_chars = token_length
            continue
        current_row.append(index)
        current_chars = projected_chars

    if current_row:
        rows.append(current_row)

    return _rebalance_rows(tokens, rows, config)


def _enumerate_caption_rows(
    tokens: Sequence[str],
    visible_indices: Sequence[int],
    config: SubtitleConfig,
) -> list[list[list[int]]]:
    partitions: list[list[list[int]]] = []

    def search(start: int, current: list[list[int]]) -> None:
        remaining = len(visible_indices) - start
        if remaining == 0:
            partitions.append([list(row) for row in current])
            return

        rows_left = config.max_lines_per_caption - len(current)
        if rows_left <= 0:
            return

        min_take = max(1, remaining - ((rows_left - 1) * config.max_words_per_line))
        max_take = min(config.max_words_per_line, remaining)

        for size in range(min_take, max_take + 1):
            row = list(visible_indices[start : start + size])
            row_chars = _row_char_count(tokens, row)
            if size > 1 and row_chars > config.max_chars_per_line:
                break
            if size == 1 and row_chars > config.max_chars_per_line:
                continue
            current.append(row)
            search(start + size, current)
            current.pop()

    search(0, [])
    return partitions


def _rebalance_rows(tokens: Sequence[str], rows: list[list[int]], config: SubtitleConfig) -> list[list[int]]:
    balanced_rows = [list(row) for row in rows if row]
    if len(balanced_rows) < 2:
        return balanced_rows

    changed = True
    while changed:
        changed = False
        for index in range(len(balanced_rows) - 1):
            leading_row = balanced_rows[index]
            trailing_row = balanced_rows[index + 1]
            if len(leading_row) <= 1 or len(trailing_row) >= config.max_words_per_line:
                continue
            if len(leading_row) - len(trailing_row) < 2 and not (
                len(trailing_row) == 1 and len(leading_row) >= 3
            ):
                continue

            moved_index = leading_row[-1]
            candidate_leading = leading_row[:-1]
            candidate_trailing = [moved_index, *trailing_row]
            if not candidate_leading:
                continue
            if _row_char_count(tokens, candidate_leading) > config.max_chars_per_line:
                continue
            if _row_char_count(tokens, candidate_trailing) > config.max_chars_per_line:
                continue

            before_delta = abs(len(leading_row) - len(trailing_row))
            after_delta = abs(len(candidate_leading) - len(candidate_trailing))
            if after_delta > before_delta:
                continue

            balanced_rows[index] = candidate_leading
            balanced_rows[index + 1] = candidate_trailing
            changed = True

    return balanced_rows


def _row_char_count(tokens: Sequence[str], indices: Sequence[int]) -> int:
    values = [tokens[index].strip() for index in indices if tokens[index].strip()]
    if not values:
        return 0
    return len(" ".join(values))


def _score_row_partition(tokens: Sequence[str], rows: Sequence[Sequence[int]]) -> float:
    widths = [_row_char_count(tokens, row) for row in rows]
    if not widths:
        return float("inf")

    max_width = max(widths)
    average_width = sum(widths) / len(widths)
    score = float((len(rows) - 1) * 12)
    score += float(max_width - min(widths)) * 2.4
    score += sum(abs(width - average_width) for width in widths)

    if len(rows) > 1 and widths[-1] < (max_width * 0.58):
        score += 8.0

    for index, row in enumerate(rows):
        words = [tokens[token_index].strip() for token_index in row if tokens[token_index].strip()]
        if not words:
            continue
        if len(words) == 1 and len(rows) > 1:
            score += 14.0 if index < len(rows) - 1 else 10.0
        for token in words[:-1]:
            if token.endswith(_TERMINAL_PUNCTUATION):
                score += 16.0
            elif token.endswith(_ROW_BREAK_PUNCTUATION):
                score += 7.0
        first_word = _normalize_break_token(words[0])
        last_word = _normalize_break_token(words[-1])
        if index > 0 and first_word in _WEAK_BREAK_STARTS:
            score += 7.0
        if index < len(rows) - 1 and last_word in _WEAK_BREAK_ENDS:
            score += 6.0
        if index < len(rows) - 1 and words[-1].endswith(_TERMINAL_PUNCTUATION):
            score -= 4.0
        elif index < len(rows) - 1 and words[-1].endswith(_ROW_BREAK_PUNCTUATION):
            score -= 1.5

    return score


def _normalize_break_token(token: str) -> str:
    return token.strip(".,!?;:\"'()[]{}").lower()


def _choose_group_end(segment: TranscriptSegment, start_index: int, config: SubtitleConfig) -> int:
    end_index = start_index
    total_words = len(segment.words)
    pause_threshold = config.pause_threshold_ms / 1000

    while end_index < total_words:
        candidate_words = list(segment.words[start_index : end_index + 1])
        if len(candidate_words) > 1 and _exceeds_group_budget(candidate_words, config):
            break

        end_index += 1
        if end_index >= total_words:
            break

        current_words = list(segment.words[start_index:end_index])
        next_gap = max(segment.words[end_index].start - current_words[-1].end, 0.0)
        if len(current_words) >= config.min_words_per_caption and current_words[-1].text.endswith(_TERMINAL_PUNCTUATION):
            break
        if len(current_words) >= config.min_words_per_caption and next_gap >= pause_threshold:
            break
        if len(current_words) >= config.target_words_per_caption:
            next_word = segment.words[end_index]
            candidate_with_next = list(segment.words[start_index : end_index + 1])
            if not (
                len(current_words) < config.max_words_per_caption
                and next_word.text.endswith(_TERMINAL_PUNCTUATION)
                and not _exceeds_group_budget(candidate_with_next, config)
            ):
                break

    return max(end_index, start_index + 1)


def _exceeds_group_budget(words: Sequence[object], config: SubtitleConfig) -> bool:
    if len(words) > config.max_words_per_caption:
        return True
    rows = build_caption_rows([getattr(word, "text", str(word)) for word in words], config)
    if len(rows) > config.max_lines_per_caption:
        return True
    start = getattr(words[0], "start", 0.0)
    end = getattr(words[-1], "end", start)
    return (end - start) > config.max_caption_duration_seconds
