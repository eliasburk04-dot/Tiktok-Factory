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
from .utils.text import first_sentence, summarize_text

_CLAUSE_SPLIT_PATTERN = re.compile(r"(?:,|;|:|\buntil\b|\bbecause\b|\bbut\b|\bafter\b|\bwhen\b|\band\b)", re.IGNORECASE)
_LOCATION_PATTERN = re.compile(
    r"\b(attic door|basement door|locked attic|basement|attic|door|hallway|closet|window|stairs|room)\b",
    re.IGNORECASE,
)


class StoryScriptBuilder:
    def __init__(self, pacing: StoryPacingConfig | None = None) -> None:
        self.pacing = pacing or StoryPacingConfig()

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
        """V4: Use the original Reddit story text verbatim — no AI rewriting,
        no clause-splitting filler.  The authentic voice is what makes these
        stories resonate."""

        # Use title as-is for the hook, body as-is for narration.
        hook_text = candidate.title.strip()
        body_text = candidate.body.strip()

        # If the body is empty (link post), fall back to the title.
        if not body_text:
            body_text = hook_text

        # Build narration: title followed by the full original body.
        narration = f"{hook_text}. {body_text}"

        # Split body into natural paragraphs / sentences for pacing segments.
        raw_paragraphs = [p.strip() for p in body_text.split("\n") if p.strip()]
        if not raw_paragraphs:
            raw_paragraphs = [body_text]

        segments: list[StorySegment] = [
            StorySegment(stage="hook", text=hook_text, pause_after_ms=self.pacing.intro_pause_ms),
        ]
        for para in raw_paragraphs:
            segments.append(
                StorySegment(stage="context", text=para, pause_after_ms=self.pacing.mid_pause_ms),
            )
        segments.append(
            StorySegment(stage="cta", text="Follow for more stories like this.", pause_after_ms=0),
        )

        setup = raw_paragraphs[0] if raw_paragraphs else ""
        tension = " ".join(raw_paragraphs[1:3]) if len(raw_paragraphs) > 1 else ""
        payoff = " ".join(raw_paragraphs[3:]) if len(raw_paragraphs) > 3 else raw_paragraphs[-1] if raw_paragraphs else ""
        cta = segments[-1].text
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
