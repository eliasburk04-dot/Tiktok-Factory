from __future__ import annotations

import base64
from pathlib import Path

import pytest

from tictoc_factory.audio.providers import BaseTTSProvider, ElevenLabsTTSProvider, MacOSTTSProvider, OpenAITTSProvider, build_tts_provider
from tictoc_factory.models import ProviderConfig, StorySegment, TTSConfig


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


def test_elevenlabs_synthesizes_story_segments_individually_with_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured_calls: list[dict[str, object]] = []

    def build_alignment(text: str) -> dict[str, object]:
        cursor = 0.0
        chars: list[str] = []
        starts: list[float] = []
        ends: list[float] = []
        for char in text:
            chars.append(char)
            starts.append(cursor)
            cursor += 0.04 if char.strip() else 0.02
            ends.append(cursor)
        return {
            "characters": chars,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        }

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    def fake_post(url: str, *, headers, json, timeout):
        captured_calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        text = str(json["text"])
        return FakeResponse(
            {
                "audio_base64": base64.b64encode(f"audio:{text}".encode()).decode("ascii"),
                "alignment": build_alignment(text),
            }
        )

    monkeypatch.setattr("tictoc_factory.audio.providers.requests.post", fake_post)
    monkeypatch.setattr(
        "tictoc_factory.audio.providers.probe_duration",
        lambda path: {
            "segment-0-normalized.wav": 0.82,
            "segment-1-normalized.wav": 0.94,
            "speech.wav": 2.01,
        }.get(path.name, 0.12),
    )

    provider = ElevenLabsTTSProvider(
        TTSConfig(provider="elevenlabs", sentence_pause_ms=120, speech_speed=1.2),
        ProviderConfig(elevenlabs_api_key_env="ELEVENLABS_API_KEY", openai_timeout_seconds=45),
        {"ELEVENLABS_API_KEY": "test-key"},
    )
    monkeypatch.setattr(provider, "_convert_to_wav", lambda source, output: output.write_bytes(source.read_bytes()))
    monkeypatch.setattr(provider, "_create_silence", lambda duration, output: output.write_bytes(f"silence:{duration}".encode()))
    monkeypatch.setattr(provider, "_concat_wav_files", lambda paths, output: output.write_bytes(b"combined"))
    monkeypatch.setattr(provider, "_normalize_audio", lambda source, output: output.write_bytes(source.read_bytes()))

    result = provider.synthesize(
        "Ignored when explicit segments are provided.",
        tmp_path / "speech.wav",
        segments=[
            StorySegment(stage="hook", text="First line.", pause_after_ms=250),
            StorySegment(stage="context", text="Second line lands.", pause_after_ms=0),
        ],
    )

    assert len(captured_calls) == 2
    assert captured_calls[0]["json"] == {
        "text": "First line.",
        "model_id": "eleven_flash_v2_5",
        "output_format": "mp3_44100_128",
        "voice_settings": {"speed": 1.2},
        "next_text": "Second line lands.",
    }
    assert captured_calls[1]["json"] == {
        "text": "Second line lands.",
        "model_id": "eleven_flash_v2_5",
        "output_format": "mp3_44100_128",
        "voice_settings": {"speed": 1.2},
        "previous_text": "First line.",
    }
    assert result.duration_seconds == 2.01
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 0.82
    assert result.segments[0].words[-1].text == "line."
    assert result.segments[1].start == pytest.approx(1.07)
    assert result.segments[1].words[0].start == pytest.approx(1.07)
    assert [word.text for word in result.segments[1].words] == ["Second", "line", "lands."]


def test_elevenlabs_clamps_voice_speed_to_supported_range(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured_payloads: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "audio_base64": base64.b64encode(b"audio").decode("ascii"),
                "alignment": {},
            }

    def fake_post(url: str, *, headers, json, timeout):
        captured_payloads.append(json)
        return FakeResponse()

    monkeypatch.setattr("tictoc_factory.audio.providers.requests.post", fake_post)
    monkeypatch.setattr("tictoc_factory.audio.providers.probe_duration", lambda path: 0.5)

    provider = ElevenLabsTTSProvider(
        TTSConfig(provider="elevenlabs", speech_speed=1.8),
        ProviderConfig(elevenlabs_api_key_env="ELEVENLABS_API_KEY", openai_timeout_seconds=45),
        {"ELEVENLABS_API_KEY": "test-key"},
    )
    monkeypatch.setattr(provider, "_convert_to_wav", lambda source, output: output.write_bytes(source.read_bytes()))
    monkeypatch.setattr(provider, "_concat_wav_files", lambda paths, output: output.write_bytes(b"combined"))
    monkeypatch.setattr(provider, "_normalize_audio", lambda source, output: output.write_bytes(source.read_bytes()))

    provider.synthesize("Faster please.", tmp_path / "speech.wav")

    assert captured_payloads[0]["voice_settings"] == {"speed": 1.2}
