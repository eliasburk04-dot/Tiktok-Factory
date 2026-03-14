from __future__ import annotations

import re

from .models import (
    ClipCandidate,
    ContentCandidate,
    HookOutput,
    ModeName,
    ScriptArtifact,
    StoryPacingConfig,
    StorySegment,
    StoryStage,
)
from .utils.text import chunk_words, expand_abbreviations, first_sentence, normalize_spacing, sanitize_narration_text, summarize_text

_CLAUSE_SPLIT_PATTERN = re.compile(r"(?:,|;|:|\buntil\b|\bbecause\b|\bbut\b|\bafter\b|\bwhen\b|\band\b)", re.IGNORECASE)
_LOCATION_PATTERN = re.compile(
    r"\b(attic door|basement door|locked attic|basement|attic|door|hallway|closet|window|stairs|room)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


class StoryScriptBuilder:
    def __init__(self, pacing: StoryPacingConfig | None = None) -> None:
        self.pacing = pacing or StoryPacingConfig()

    def target_reddit_story_character_range(self) -> tuple[int, int]:
        minimum = round((self.pacing.target_duration_seconds_min / 60) * self.pacing.estimated_characters_per_minute)
        maximum = round((self.pacing.target_duration_seconds_max / 60) * self.pacing.estimated_characters_per_minute)
        return minimum, max(minimum, maximum)

    def supports_target_duration(self, candidate: ContentCandidate, *, mode: ModeName) -> bool:
        if mode != "reddit_story_gameplay":
            return True
        minimum_chars, _ = self.target_reddit_story_character_range()
        narration_source = self._normalize_story_text(
            f"{candidate.title}. {self._sanitize_reddit_story_text(candidate.body)}"
        )
        return len(narration_source) >= minimum_chars

    def build(
        self,
        candidate: ContentCandidate,
        hook: HookOutput,
        *,
        mode: ModeName,
        clip: ClipCandidate | None = None,
    ) -> ScriptArtifact:
        if mode == "reddit_story_gameplay":
            return self._build_reddit_story(candidate, hook)

        premise = first_sentence(candidate.body)
        setup = f"Source: r/{candidate.subreddit}. {premise}"
        tension = summarize_text(candidate.body, word_limit=40)
        payoff = clip.summary if clip else f"The comment section exploded because {premise.lower()}."
        cta = "Follow for the next story and save this if the twist caught you."
        narration = " ".join([hook.text, setup, tension, payoff, cta])
        summary = clip.summary if clip else summarize_text(candidate.body, word_limit=18)
        segments = [
            StorySegment(stage="hook", text=hook.text, pause_after_ms=self.pacing.intro_pause_ms),
            StorySegment(stage="context", text=setup, pause_after_ms=self.pacing.mid_pause_ms),
            StorySegment(stage="escalation", text=tension, pause_after_ms=self.pacing.mid_pause_ms),
            StorySegment(stage="final_twist", text=payoff, pause_after_ms=self.pacing.final_pause_ms),
            StorySegment(stage="cta", text=cta, pause_after_ms=0),
        ]
        if mode == "longform_clip":
            setup = f"Podcast clip setup: {summary}"
            payoff = clip.summary if clip else summary
        return ScriptArtifact(
            hook=hook.text,
            setup=setup,
            tension=tension,
            payoff=payoff,
            cta=cta,
            narration=narration,
            summary=summary,
            segments=segments,
        )

    def _build_reddit_story(self, candidate: ContentCandidate, hook: HookOutput) -> ScriptArtifact:
        hook_text = self._normalize_story_text(candidate.title.strip())
        body_text = self._sanitize_reddit_story_text(candidate.body.strip())

        if not body_text:
            body_text = hook_text

        cta = "Follow for more stories like this."
        selected_units = self._select_reddit_story_units(hook_text, body_text, cta)
        segments: list[StorySegment] = [
            StorySegment(stage="hook", text=hook_text, pause_after_ms=self.pacing.intro_pause_ms),
        ]
        for index, unit in enumerate(selected_units):
            segments.append(
                StorySegment(
                    stage=self._reddit_stage_for_index(index, len(selected_units)),
                    text=unit,
                    pause_after_ms=self.pacing.final_pause_ms if index == len(selected_units) - 1 else self.pacing.mid_pause_ms,
                ),
            )
        segments.append(StorySegment(stage="cta", text=cta, pause_after_ms=0))

        normalized_body = self._normalize_story_text(body_text)
        setup = selected_units[0] if selected_units else normalized_body
        tension = " ".join(selected_units[1:-1]) if len(selected_units) > 2 else (selected_units[1] if len(selected_units) > 1 else "")
        payoff = selected_units[-1] if selected_units else normalized_body
        narration = " ".join(segment.text for segment in segments).strip()
        summary = summarize_text(narration, word_limit=18)

        return ScriptArtifact(
            hook=hook_text,
            setup=setup,
            tension=tension,
            payoff=payoff,
            cta=cta,
            narration=narration,
            summary=summary,
            segments=segments,
        )

    def _select_reddit_story_units(self, hook_text: str, body_text: str, cta_text: str) -> list[str]:
        units = self._split_reddit_story_units(body_text)
        if not units:
            return [self._normalize_story_text(body_text)]

        minimum_chars, maximum_chars = self.target_reddit_story_character_range()
        fixed_chars = len(self._normalize_story_text(hook_text)) + len(self._normalize_story_text(cta_text)) + 2
        minimum_body_chars = max(minimum_chars - fixed_chars, 0)
        maximum_body_chars = max(maximum_chars - fixed_chars, minimum_body_chars)
        hard_max_chars = max(round(maximum_body_chars * 1.12), maximum_body_chars)

        selected: list[str] = []
        current_chars = 0
        for unit in units:
            normalized_unit = self._normalize_story_text(unit)
            if not normalized_unit:
                continue
            proposed_chars = current_chars + len(normalized_unit) + (1 if selected else 0)
            if proposed_chars <= maximum_body_chars:
                selected.append(normalized_unit)
                current_chars = proposed_chars
                continue
            if current_chars < minimum_body_chars and proposed_chars <= hard_max_chars:
                selected.append(normalized_unit)
                current_chars = proposed_chars
            break

        if not selected:
            return [self._trim_story_unit(units[0], max(maximum_body_chars, minimum_body_chars, 1))]
        return selected

    def _split_reddit_story_units(self, body_text: str) -> list[str]:
        cleaned_body = self._sanitize_reddit_story_text(body_text)
        paragraphs = [self._normalize_story_text(paragraph) for paragraph in cleaned_body.splitlines() if paragraph.strip()]
        if not paragraphs:
            paragraphs = [self._normalize_story_text(cleaned_body)]

        units: list[str] = []
        max_chunk_words = max(self.pacing.max_segment_words * 2, 20)
        for paragraph in paragraphs:
            for sentence in _SENTENCE_SPLIT_PATTERN.split(paragraph):
                normalized_sentence = self._normalize_story_text(sentence)
                if not normalized_sentence:
                    continue
                if len(normalized_sentence.split()) <= max_chunk_words:
                    units.append(normalized_sentence)
                    continue
                units.extend(chunk_words(normalized_sentence, chunk_size=max_chunk_words))
        return units

    def _trim_story_unit(self, value: str, maximum_chars: int) -> str:
        normalized = self._normalize_story_text(value)
        if len(normalized) <= maximum_chars:
            return normalized
        clipped = normalized[:maximum_chars].rsplit(" ", 1)[0].strip()
        return clipped or normalized[:maximum_chars].strip()

    def _normalize_story_text(self, value: str) -> str:
        cleaned = normalize_spacing(sanitize_narration_text(value))
        return expand_abbreviations(cleaned)

    def _sanitize_reddit_story_text(self, value: str) -> str:
        return sanitize_narration_text(value, drop_navigation_lines=True)

    def _reddit_stage_for_index(self, index: int, total_units: int) -> StoryStage:
        if total_units <= 1:
            return "final_twist"
        if index == 0:
            return "context"
        if index == total_units - 1:
            return "final_twist"
        return "escalation"

    def _build_hook_text(self, title_clauses: list[str], fallback_hook: str) -> str:
        if len(title_clauses) >= 2:
            first_hook = self._sentence(title_clauses[0], max_words=self.pacing.hook_max_words)
            second_hook = self._sentence(title_clauses[1], max_words=self.pacing.hook_max_words)
            return f"{first_hook} {second_hook}"
        if title_clauses:
            return self._sentence(title_clauses[0], max_words=self.pacing.hook_max_words)
        return self._sentence(fallback_hook, max_words=self.pacing.hook_max_words)

    def _split_clauses(self, value: str) -> list[str]:
        chunks = _CLAUSE_SPLIT_PATTERN.split(value)
        clauses: list[str] = []
        for chunk in chunks:
            cleaned = " ".join(chunk.replace("\n", " ").split()).strip(" .!?\"'")
            if len(cleaned.split()) < 3:
                continue
            clauses.append(cleaned)
        return clauses

    def _sentence(self, value: str, *, max_words: int | None = None) -> str:
        words = value.split()
        limited = " ".join(words[: max_words or self.pacing.max_segment_words]).strip(" .!?")
        if not limited:
            return ""
        normalized = limited[0].upper() + limited[1:]
        if normalized.endswith(("!", "?")):
            return normalized
        return f"{normalized}."

    def _extract_location(self, title: str, body: str) -> str:
        match = _LOCATION_PATTERN.search(f"{title} {body}")
        if not match:
            return "door"
        return match.group(1).lower()
