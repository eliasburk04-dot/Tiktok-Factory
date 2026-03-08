from __future__ import annotations

from dataclasses import dataclass

from ..models import ContentCandidate, HookOutput
from ..utils.text import summarize_text


@dataclass(frozen=True)
class HookTemplate:
    template_id: str
    style_tag: str
    template: str


class HookGenerator:
    def __init__(self) -> None:
        self.templates: list[HookTemplate] = [
            HookTemplate("hook-01", "shock", "This story starts normal, then {title}."),
            HookTemplate("hook-02", "confession", "Reddit could not stop reading this: {title}."),
            HookTemplate("hook-03", "question", "Would you keep watching after this: {title}?"),
            HookTemplate("hook-04", "fear", "The creepiest detail is not the title, it is this: {summary}."),
            HookTemplate("hook-05", "stakes", "This is the moment everything goes wrong: {title}."),
            HookTemplate("hook-06", "conflict", "One sentence ruined the whole situation: {summary}."),
            HookTemplate("hook-07", "drama", "If this happened to you, what would you do: {title}?"),
            HookTemplate("hook-08", "mystery", "Nobody knew why this happened until the last line."),
            HookTemplate("hook-09", "urgency", "Stay for the twist because this escalates fast."),
            HookTemplate("hook-10", "opinion", "I still cannot decide who was actually wrong here."),
            HookTemplate("hook-11", "shock", "This might be the wildest Reddit post from {subreddit}."),
            HookTemplate("hook-12", "confession", "This confession gets worse every few seconds."),
            HookTemplate("hook-13", "mystery", "The first sentence sounds fake, but the details are brutal."),
            HookTemplate("hook-14", "stakes", "The part nobody expected is what happens next."),
            HookTemplate("hook-15", "question", "Why would anyone admit this online?"),
            HookTemplate("hook-16", "fear", "This is exactly how a harmless night turns bad."),
            HookTemplate("hook-17", "drama", "Every comment said the same thing after reading this."),
            HookTemplate("hook-18", "shock", "This line stopped me cold: {summary}."),
            HookTemplate("hook-19", "conflict", "You can hear the argument building from the first sentence."),
            HookTemplate("hook-20", "opinion", "I need to know if you think this person crossed the line."),
            HookTemplate("hook-21", "fear", "Imagine hearing this in the dark: {summary}."),
            HookTemplate("hook-22", "mystery", "Nothing about this story should be possible."),
            HookTemplate("hook-23", "urgency", "Watch until the end because the last reveal flips everything."),
            HookTemplate("hook-24", "question", "Would you leave immediately or keep listening?"),
            HookTemplate("hook-25", "drama", "The comments split into two camps instantly."),
            HookTemplate("hook-26", "shock", "This creator said one sentence and the room lost it."),
            HookTemplate("hook-27", "opinion", "Controversial take, but this clip deserved the reaction."),
            HookTemplate("hook-28", "stakes", "The tension spikes right here: {summary}."),
            HookTemplate("hook-29", "question", "Can you guess the twist before the narrator says it?"),
            HookTemplate("hook-30", "confession", "Here is the detail they probably wish they had cut."),
        ]

    def generate(
        self,
        candidate: ContentCandidate,
        *,
        recent_template_ids: list[str],
    ) -> HookOutput:
        summary = summarize_text(candidate.body, word_limit=14)
        options = [item for item in self.templates if item.template_id not in recent_template_ids[-3:]]
        if not options:
            options = self.templates
        chosen = options[(candidate.score + len(candidate.title)) % len(options)]
        text = chosen.template.format(
            subreddit=candidate.subreddit,
            title=candidate.title.rstrip("."),
            summary=summary.rstrip("."),
        )
        return HookOutput(template_id=chosen.template_id, text=text, style_tag=chosen.style_tag)
