from __future__ import annotations

from tictoc_factory.llm.creative import OpenAICreativeDirector
from tictoc_factory.models import ClipCandidate, ContentCandidate


class FakeClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def generate_json(
        self,
        *,
        instructions: str,
        user_input: str,
        schema_name: str,
        schema: dict[str, object],
        max_output_tokens: int,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "instructions": instructions,
                "user_input": user_input,
                "schema_name": schema_name,
                "schema": schema,
                "max_output_tokens": max_output_tokens,
            }
        )
        return self.responses.pop(0)


def test_openai_creative_director_builds_hook_and_script() -> None:
    client = FakeClient(
        [
            {
                "template_id": "openai-shock-01",
                "style_tag": "shock",
                "hook": "This one line changes the whole story.",
                "setup": "A Reddit user heard a whisper behind a locked attic door.",
                "tension": "Each night the voice used more personal details.",
                "payoff": "The final reveal implies someone had been living above them.",
                "cta": "Follow for the next twist.",
                "summary": "A whisper in a locked attic gets personal.",
                "narration": (
                    "This one line changes the whole story. "
                    "A Reddit user heard a whisper behind a locked attic door. "
                    "Each night the voice used more personal details. "
                    "The final reveal implies someone had been living above them. "
                    "Follow for the next twist."
                ),
            }
        ]
    )
    director = OpenAICreativeDirector(client)
    candidate = ContentCandidate(
        id="story-1",
        subreddit="nosleep",
        title="I heard my name from the attic",
        body="It started after midnight and got worse every night after that.",
        score=12000,
        num_comments=800,
        created_utc=1730985600,
    )

    hook, script, metadata = director.generate_story_package(candidate=candidate, mode="reddit_story_gameplay")

    assert hook.template_id == "openai-shock-01"
    assert script.hook == "This one line changes the whole story."
    assert "attic" in script.setup.lower()
    assert metadata["provider"] == "openai"
    assert client.calls[0]["schema_name"] == "creative_package"


def test_openai_creative_director_reranks_clip_candidates() -> None:
    client = FakeClient([{"best_index": 1, "reason": "This segment has the strongest conflict and payoff."}])
    director = OpenAICreativeDirector(client)
    candidate = ContentCandidate(
        id="podcast-1",
        subreddit="longform",
        title="Clip from episode 10",
        body="Founder story",
        score=1000,
        num_comments=0,
        created_utc=1730985600,
    )
    clips = [
        ClipCandidate(
            start=0.0,
            end=25.0,
            score=8.1,
            summary="The host introduces the failure.",
            transcript_excerpt="We are discussing the failure.",
            reasons=["emotion_hits=1"],
        ),
        ClipCandidate(
            start=25.0,
            end=50.0,
            score=7.9,
            summary="The founder admits the product catches fire.",
            transcript_excerpt="Would you invest if I told you the product catches fire.",
            reasons=["emotion_hits=2"],
        ),
    ]

    chosen = director.rerank_clips(candidate=candidate, clips=clips)

    assert chosen.start == 25.0
    assert chosen.end == 50.0
