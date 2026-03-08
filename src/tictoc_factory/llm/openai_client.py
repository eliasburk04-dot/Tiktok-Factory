from __future__ import annotations

import json
from typing import Any

import requests


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: int = 45,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")

    def generate_json(
        self,
        *,
        instructions: str,
        user_input: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "store": False,
            "instructions": instructions,
            "input": user_input,
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        if self.model.startswith("gpt-5"):
            payload["reasoning"] = {"effort": "low"}
            payload["text"]["verbosity"] = "medium"

        response = requests.post(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return json.loads(self._extract_output_text(response.json()))

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        direct_output = payload.get("output_text")
        if isinstance(direct_output, str) and direct_output.strip():
            return direct_output

        parts: list[str] = []
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])

        text = "".join(parts).strip()
        if not text:
            raise ValueError("OpenAI response did not include output text")
        return text
