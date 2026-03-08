from __future__ import annotations

from pathlib import Path

from tictoc_factory.audio.providers import BaseTTSProvider, ElevenLabsTTSProvider, MacOSTTSProvider, OpenAITTSProvider, build_tts_provider
from tictoc_factory.models import ProviderConfig, TTSConfig


class DummyTTSProvider(BaseTTSProvider):
    def _render_segment_audio(self, text: str, output_path: Path) -> None:
        output_path.write_bytes(b"")


def test_build_tts_provider_auto_prefers_openai_when_key_is_present(monkeypatch) -> None:
    monkeypatch.setattr("tictoc_factory.audio.providers._has_command", lambda command: command == "say")

    provider = build_tts_provider(
        TTSConfig(provider="auto"),
        ProviderConfig(),
        {"OPENAI_API_KEY": "test-key"},
    )

    assert isinstance(provider, OpenAITTSProvider)

def test_build_tts_provider_resolves_elevenlabs_when_auto_and_key_present() -> None:
    config = TTSConfig(provider="auto")
    providers = ProviderConfig()
    env = {"ELEVENLABS_API_KEY": "test-key"}

    provider = build_tts_provider(config, providers, env)

    assert isinstance(provider, ElevenLabsTTSProvider)

def test_build_tts_provider_resolves_macos_when_auto_and_no_key_and_say_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tictoc_factory.audio.providers._has_command", lambda command: command == "say")

    provider = build_tts_provider(
        TTSConfig(provider="auto"),
        ProviderConfig(openai_api_key_env="OPENAI_API_KEY"),
        {},
    )

    assert isinstance(provider, MacOSTTSProvider)


def test_openai_tts_uses_configured_voice_and_speed(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"RIFFfake"

        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("tictoc_factory.audio.providers.requests.post", fake_post)

    provider = OpenAITTSProvider(
        TTSConfig(provider="openai", openai_voice="alloy", speech_speed=1.03),
        ProviderConfig(openai_api_key_env="OPENAI_API_KEY", openai_timeout_seconds=45),
        {"OPENAI_API_KEY": "test-key"},
    )
    output_path = tmp_path / "speech.wav"

    provider._render_segment_audio("Tell the story naturally.", output_path)

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["voice"] == "alloy"
    assert payload["speed"] == 1.03
    assert payload["instructions"] == TTSConfig(speech_speed=1.03).openai_instructions
    assert output_path.read_bytes() == b"RIFFfake"


def test_deterministic_word_timings_cover_segment_without_gaps() -> None:
    provider = DummyTTSProvider(TTSConfig(), ProviderConfig(), {})

    words = provider._build_deterministic_word_timings(
        "Never open the basement door after midnight.",
        start=1.25,
        end=3.75,
    )

    assert [word.text for word in words] == ["Never", "open", "the", "basement", "door", "after", "midnight."]
    assert words[0].start == 1.25
    assert words[-1].end == 3.75
    assert all(word.start < word.end for word in words)
    assert all(words[index].end <= words[index + 1].start for index in range(len(words) - 1))
