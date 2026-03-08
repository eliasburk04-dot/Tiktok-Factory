from __future__ import annotations

from tictoc_factory.hooks.generator import HookGenerator
from tictoc_factory.models import ContentCandidate


def test_hook_generator_rotates_templates_without_immediate_repeat() -> None:
    generator = HookGenerator()
    candidate = ContentCandidate(
        id="story-1",
        subreddit="nosleep",
        title="I found a locked room in my basement",
        body="It should not have been there.",
        score=5000,
        num_comments=300,
        created_utc=1730985600,
    )

    first = generator.generate(candidate, recent_template_ids=[])
    second = generator.generate(candidate, recent_template_ids=[first.template_id])

    assert first.template_id != second.template_id
    assert first.text
    assert second.text


def test_hook_generator_exposes_at_least_twenty_five_templates() -> None:
    generator = HookGenerator()

    assert len(generator.templates) >= 25
