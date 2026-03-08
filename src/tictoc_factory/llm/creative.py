from __future__ import annotations

import json
from typing import Any, Protocol

from ..models import ClipCandidate, ContentCandidate, HookOutput, ModeName, ScriptArtifact
from .openai_client import OpenAIResponsesClient


class StructuredTextClient(Protocol):
    def generate_json(
        self,
        *,
        instructions: str,
        user_input: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> dict[str, Any]:
        """Return a validated JSON-like object from the model."""
        ...


class OpenAICreativeDirector:
    def __init__(self, client: StructuredTextClient) -> None:
        self.client = client

    def generate_story_package(
        self,
        *,
        candidate: ContentCandidate,
        mode: ModeName,
        clip: ClipCandidate | None = None,
    ) -> tuple[HookOutput, ScriptArtifact, dict[str, str]]:
        payload = self.client.generate_json(
            instructions=(
                "You are writing short-form video creative for TikTok-style clips. "
                "Return concise, high-retention English copy with a strong first line, clear escalation, "
                "a payoff, and a short CTA. Avoid hashtags, emojis, and platform policy risks."
            ),
            user_input=json.dumps(
                {
                    "mode": mode,
                    "candidate": candidate.model_dump(mode="json"),
                    "clip": clip.model_dump(mode="json") if clip else None,
                },
                indent=2,
                sort_keys=True,
            ),
            schema_name="creative_package",
            schema=_creative_package_schema(),
            max_output_tokens=700,
        )
        hook = HookOutput(
            template_id=str(payload["template_id"]),
            text=str(payload["hook"]),
            style_tag=str(payload["style_tag"]),
        )
        script = ScriptArtifact(
            hook=str(payload["hook"]),
            setup=str(payload["setup"]),
            tension=str(payload["tension"]),
            payoff=str(payload["payoff"]),
            cta=str(payload["cta"]),
            narration=str(payload["narration"]),
            summary=str(payload["summary"]),
        )
        return hook, script, {"provider": "openai", "model": str(getattr(self.client, "model", "unknown"))}

    def rerank_clips(self, *, candidate: ContentCandidate, clips: list[ClipCandidate]) -> ClipCandidate:
        if len(clips) == 1:
            return clips[0]
        payload = self.client.generate_json(
            instructions=(
                "Choose the single best short-form clip candidate for retention. "
                "Prefer strong conflict, surprise, emotional spikes, and clean standalone payoff."
            ),
            user_input=json.dumps(
                {
                    "candidate": candidate.model_dump(mode="json"),
                    "clip_options": [
                        {"index": index, **clip.model_dump(mode="json")} for index, clip in enumerate(clips)
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            schema_name="clip_rerank",
            schema=_clip_rerank_schema(len(clips)),
            max_output_tokens=250,
        )
        best_index = int(payload["best_index"])
        if best_index < 0 or best_index >= len(clips):
            raise ValueError(f"OpenAI returned invalid clip index: {best_index}")
        return clips[best_index]


def build_openai_creative_director(
    *,
    api_key: str | None,
    model: str,
    timeout_seconds: int,
) -> OpenAICreativeDirector | None:
    if not api_key:
        return None
    client = OpenAIResponsesClient(api_key=api_key, model=model, timeout_seconds=timeout_seconds)
    return OpenAICreativeDirector(client)


def _creative_package_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "template_id": {"type": "string"},
            "style_tag": {"type": "string"},
            "hook": {"type": "string"},
            "setup": {"type": "string"},
            "tension": {"type": "string"},
            "payoff": {"type": "string"},
            "cta": {"type": "string"},
            "summary": {"type": "string"},
            "narration": {"type": "string"},
        },
        "required": [
            "template_id",
            "style_tag",
            "hook",
            "setup",
            "tension",
            "payoff",
            "cta",
            "summary",
            "narration",
        ],
    }


def _clip_rerank_schema(option_count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "best_index": {"type": "integer", "minimum": 0, "maximum": max(option_count - 1, 0)},
            "reason": {"type": "string"},
        },
        "required": ["best_index", "reason"],
    }
