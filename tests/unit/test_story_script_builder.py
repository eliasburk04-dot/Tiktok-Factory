from __future__ import annotations

from tictoc_factory.models import ClipCandidate, ContentCandidate, HookOutput, StoryPacingConfig
from tictoc_factory.script_builder import StoryScriptBuilder


def test_story_script_builder_rewrites_reddit_story_with_short_suspense_segments() -> None:
    builder = StoryScriptBuilder(StoryPacingConfig())
    candidate = ContentCandidate(
        id="story-1",
        subreddit="nosleep",
        title="I opened the attic door and something whispered my name",
        body=(
            "I never told anyone about the locked attic until the whisper came back "
            "the second night and used my full name."
        ),
        score=18000,
        num_comments=900,
        created_utc=1730985600,
    )
    hook = HookOutput(template_id="hook-22", text="Nothing about this story should be possible.", style_tag="mystery")

    script = builder.build(candidate, hook, mode="reddit_story_gameplay")

    # V4: verbatim mode — hook is the original title, body is passed through unchanged
    assert script.segments[0].stage == "hook"
    assert script.segments[0].text == candidate.title
    assert script.segments[-1].stage == "cta"
    # Narration must contain the original body text word-for-word
    assert candidate.body in script.narration
    # The original title must appear in the narration
    assert candidate.title in script.narration


def test_story_script_builder_keeps_longform_mode_structured() -> None:
    builder = StoryScriptBuilder(StoryPacingConfig())
    candidate = ContentCandidate(
        id="clip-1",
        subreddit="longform",
        title="Clip from episode 10",
        body="The host explains why the launch went wrong and what happened next.",
        score=1000,
        num_comments=0,
        created_utc=1730985600,
    )
    hook = HookOutput(template_id="hook-08", text="Nobody knew why this happened until the last line.", style_tag="mystery")
    clip = ClipCandidate(
        start=12.0,
        end=42.0,
        score=8.4,
        summary="The founder admits the product caught fire during the demo.",
        transcript_excerpt="The founder admits the product caught fire during the demo.",
        reasons=["conflict"],
    )

    script = builder.build(candidate, hook, mode="longform_clip", clip=clip)

    assert script.hook == hook.text
    assert script.setup == "Podcast clip setup: The founder admits the product caught fire during the demo."
    assert script.payoff == clip.summary
    assert script.segments[0].stage == "hook"
    assert script.segments[-1].stage == "cta"
    assert any(segment.stage == "escalation" for segment in script.segments)
