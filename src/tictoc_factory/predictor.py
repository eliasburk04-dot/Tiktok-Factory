from __future__ import annotations

from .models import ClipCandidate, ScriptArtifact, ViralScoreResult


class PrePublishPredictor:
    def predict(
        self,
        *,
        script: ScriptArtifact,
        source_score: ViralScoreResult,
        clip: ClipCandidate | None,
    ) -> dict[str, float | list[str]]:
        clip_bonus = min((clip.score / 10.0), 2.0) if clip else 0.5
        readability = 1.2 if len(script.narration.split()) <= 140 else 0.7
        hook_bonus = 1.5 if "?" in script.hook or "wildest" in script.hook.lower() else 0.8
        total = min(source_score.normalized * 5 + clip_bonus + readability + hook_bonus, 10.0)
        return {
            "score": round(total, 2),
            "reasons": [
                f"source={source_score.normalized:.2f}",
                f"clip_bonus={clip_bonus:.2f}",
                f"readability={readability:.2f}",
                f"hook_bonus={hook_bonus:.2f}",
            ],
        }
