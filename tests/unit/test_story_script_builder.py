from __future__ import annotations

from tictoc_factory.models import ClipCandidate, ContentCandidate, HookOutput, StoryPacingConfig
from tictoc_factory.script_builder import StoryScriptBuilder


def test_story_script_builder_trims_reddit_story_to_target_duration_window() -> None:
    builder = StoryScriptBuilder(
        StoryPacingConfig(
            target_duration_seconds_min=60,
            target_duration_seconds_max=70,
            estimated_characters_per_minute=240,
        )
    )
    candidate = ContentCandidate(
        id="story-1",
        subreddit="nosleep",
        title="I opened the attic door and something whispered my name",
        body=(
            " ".join(
                f"Paragraph {index} explains exactly how the lie started and why the neighbors kept pretending nothing was wrong."
                for index in range(1, 12)
            )
        ),
        score=18000,
        num_comments=900,
        created_utc=1730985600,
    )
    hook = HookOutput(template_id="hook-22", text="Nothing about this story should be possible.", style_tag="mystery")

    script = builder.build(candidate, hook, mode="reddit_story_gameplay")
    min_chars, max_chars = builder.target_reddit_story_character_range()

    assert script.segments[0].stage == "hook"
    assert script.segments[0].text == candidate.title
    assert script.segments[-1].stage == "cta"
    assert script.narration.startswith(candidate.title)
    assert candidate.body not in script.narration
    assert min_chars <= len(script.narration) <= max_chars + len(script.cta) + 4


def test_story_script_builder_can_reject_reddit_story_that_is_too_short_for_target_window() -> None:
    builder = StoryScriptBuilder(
        StoryPacingConfig(
            target_duration_seconds_min=65,
            target_duration_seconds_max=80,
            estimated_characters_per_minute=240,
        )
    )
    candidate = ContentCandidate(
        id="story-short",
        subreddit="confessions",
        title="I lied once.",
        body="It backfired immediately.",
        score=2200,
        num_comments=140,
        created_utc=1730985600,
    )

    assert builder.supports_target_duration(candidate, mode="reddit_story_gameplay") is False


def test_story_script_builder_strips_reddit_navigation_links_from_narration() -> None:
    builder = StoryScriptBuilder(StoryPacingConfig())
    candidate = ContentCandidate(
        id="story-links",
        subreddit="nosleep",
        title="My father raised me in a mountain cabin.",
        body=(
            "**Part I** - [Part II](https://www.reddit.com/r/nosleep/comments/example/part_ii/) "
            "- [Part III](https://www.reddit.com/r/nosleep/comments/example/part_iii/)\n\n"
            "He said the tree line was where God stopped listening.\n"
            "The note only said [listen](https://example.com/listen) before the floor started breathing."
        ),
        score=22000,
        num_comments=1400,
        created_utc=1730985600,
    )
    hook = HookOutput(template_id="hook-17", text="He trained me to fear the woods for a reason.", style_tag="dread")

    script = builder.build(candidate, hook, mode="reddit_story_gameplay")

    assert "https://" not in script.narration
    assert "reddit.com" not in script.narration
    assert "[Part II]" not in script.narration
    assert "Part II" not in script.narration
    assert "listen before the floor started breathing." in script.narration
    assert script.segments[1].text == "He said the tree line was where God stopped listening."


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
