from __future__ import annotations

import base64
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from ..models import ProviderConfig, StorySegment, TranscriptSegment, TTSConfig, WordTiming
from ..utils.files import atomic_write_text
from ..utils.process import probe_duration, run_command

_SPOKEN_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")


def _has_command(command: str) -> bool:
    return shutil.which(command) is not None


def _normalize_alignment_token(value: str) -> str:
    return "".join(_SPOKEN_WORD_PATTERN.findall(value)).lower()


@dataclass(frozen=True)
class SynthesisResult:
    path: Path
    duration_seconds: float
    segments: list[TranscriptSegment]


class BaseTTSProvider:
    def __init__(self, config: TTSConfig, providers: ProviderConfig, env: Mapping[str, str]) -> None:
        self.config = config
        self.providers = providers
        self.env = env

    def synthesize(self, text: str, output_path: Path, *, segments: Sequence[StorySegment] | None = None) -> SynthesisResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        segment_list = list(segments or [StorySegment(stage="context", text=text, pause_after_ms=self.config.sentence_pause_ms)])
        with TemporaryDirectory(dir=output_path.parent) as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            concat_paths: list[Path] = []
            timed_segments: list[TranscriptSegment] = []
            cursor = 0.0
            for index, segment in enumerate(segment_list):
                raw_path = temp_dir / f"segment-{index}{self._raw_suffix()}"
                normalized_path = temp_dir / f"segment-{index}-normalized.wav"
                self._render_segment_audio(segment.text, raw_path)
                self._convert_to_wav(raw_path, normalized_path)
                duration = probe_duration(normalized_path)
                timed_segments.append(
                    TranscriptSegment(
                        start=cursor,
                        end=cursor + duration,
                        text=segment.text,
                        words=self._build_deterministic_word_timings(segment.text, start=cursor, end=cursor + duration),
                    )
                )
                cursor += duration
                concat_paths.append(normalized_path)
                if index < len(segment_list) - 1:
                    pause_ms = segment.pause_after_ms or self.config.sentence_pause_ms
                    if pause_ms > 0:
                        silence_path = temp_dir / f"pause-{index}.wav"
                        self._create_silence(pause_ms / 1000, silence_path)
                        concat_paths.append(silence_path)
                        cursor += pause_ms / 1000

            combined_path = temp_dir / "combined.wav"
            self._concat_wav_files(concat_paths, combined_path)
            self._normalize_audio(combined_path, output_path)
            result = SynthesisResult(
                path=output_path,
                duration_seconds=probe_duration(output_path),
                segments=timed_segments,
            )
            return self._finalize_word_timings(result)

    def _render_segment_audio(self, text: str, output_path: Path) -> None:
        raise NotImplementedError

    def _finalize_word_timings(self, result: SynthesisResult) -> SynthesisResult:
        return result

    def _build_deterministic_word_timings(self, text: str, *, start: float, end: float) -> list[WordTiming]:
        tokens = text.split()
        if not tokens:
            return []
        total_duration = max(end - start, 0.05 * len(tokens))
        weights = [self._spoken_word_weight(token) for token in tokens]
        total_weight = sum(weights) or len(tokens)
        cursor = start
        timings: list[WordTiming] = []
        for index, token in enumerate(tokens):
            word_end = end if index == len(tokens) - 1 else cursor + (total_duration * (weights[index] / total_weight))
            timings.append(
                WordTiming(
                    start=cursor,
                    end=max(word_end, cursor + 0.03),
                    text=token,
                )
            )
            cursor = timings[-1].end
        if timings:
            timings[-1] = timings[-1].model_copy(update={"end": end})
        return timings

    def _spoken_word_weight(self, token: str) -> float:
        core = "".join(_SPOKEN_WORD_PATTERN.findall(token))
        weight = float(max(len(core), 1))
        if token.endswith((".", "!", "?", ",", ";", ":")):
            weight += 1.0
        return weight

    def _raw_suffix(self) -> str:
        return ".wav"

    def _convert_to_wav(self, source_path: Path, output_path: Path) -> None:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-ar",
                str(self.config.sample_rate_hz),
                "-ac",
                "1",
                str(output_path),
            ]
        )

    def _create_silence(self, duration_seconds: float, output_path: Path) -> None:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={self.config.sample_rate_hz}:cl=mono",
                "-t",
                f"{duration_seconds:.3f}",
                str(output_path),
            ]
        )

    def _concat_wav_files(self, input_paths: Sequence[Path], output_path: Path) -> None:
        list_path = output_path.with_suffix(".txt")
        atomic_write_text(list_path, "".join(f"file {path.as_posix()}\n" for path in input_paths))
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output_path),
            ]
        )

    def _normalize_audio(self, source_path: Path, output_path: Path) -> None:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-af",
                f"bass=g=3:f=100,loudnorm=I={self.config.normalize_lufs}:LRA=11:TP=-1.5",
                "-ar",
                str(self.config.sample_rate_hz),
                "-ac",
                "1",
                str(output_path),
            ]
        )


class OpenAITTSProvider(BaseTTSProvider):
    def _raw_suffix(self) -> str:
        return ".wav"

    def _render_segment_audio(self, text: str, output_path: Path) -> None:
        api_key = self.env.get(self.providers.openai_api_key_env, "").strip()
        if not api_key:
            raise ValueError(f"Missing OpenAI API key in {self.providers.openai_api_key_env}")

        response = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.openai_model,
                "voice": self.config.openai_voice,
                "input": text,
                "response_format": "wav",
                "speed": self.config.speech_speed,
                "instructions": self.config.openai_instructions,
            },
            timeout=self.providers.openai_timeout_seconds,
        )
        response.raise_for_status()
        output_path.write_bytes(response.content)

    def _finalize_word_timings(self, result: SynthesisResult) -> SynthesisResult:
        if self.config.word_timing_mode == "deterministic":
            return result
        try:
            transcribed_words = self._transcribe_word_timings(result.path)
        except Exception:
            return result
        if not transcribed_words:
            return result
        aligned_segments = self._align_transcribed_segments(result.segments, transcribed_words)
        return SynthesisResult(
            path=result.path,
            duration_seconds=result.duration_seconds,
            segments=aligned_segments,
        )

    def _transcribe_word_timings(self, audio_path: Path) -> list[WordTiming]:
        api_key = self.env.get(self.providers.openai_api_key_env, "").strip()
        if not api_key:
            return []
        with audio_path.open("rb") as audio_file:
            response = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={
                    "model": "whisper-1",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "word",
                },
                files={"file": (audio_path.name, audio_file, "audio/wav")},
                timeout=self.providers.openai_timeout_seconds,
            )
        response.raise_for_status()
        payload = response.json()
        words_payload = payload.get("words", [])
        timings: list[WordTiming] = []
        for item in words_payload:
            text = str(item.get("word", "")).strip()
            if not text:
                continue
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
            if end <= start:
                continue
            timings.append(WordTiming(start=start, end=end, text=text))
        return timings

    def _align_transcribed_segments(
        self,
        segments: Sequence[TranscriptSegment],
        transcribed_words: Sequence[WordTiming],
    ) -> list[TranscriptSegment]:
        aligned_segments: list[TranscriptSegment] = []
        for segment in segments:
            segment_words = [
                word
                for word in transcribed_words
                if segment.start - 0.08 <= ((word.start + word.end) / 2) <= segment.end + 0.08
            ]
            aligned_words = self._align_transcribed_words(segment.text.split(), segment_words)
            aligned_segments.append(
                segment.model_copy(
                    update={"words": aligned_words or segment.words},
                )
            )
        return aligned_segments

    def _align_transcribed_words(
        self,
        source_tokens: Sequence[str],
        transcribed_words: Sequence[WordTiming],
    ) -> list[WordTiming]:
        if not source_tokens or not transcribed_words:
            return []
        normalized_transcribed = [
            (_normalize_alignment_token(word.text), word)
            for word in transcribed_words
            if _normalize_alignment_token(word.text)
        ]
        if len(normalized_transcribed) < len(source_tokens):
            return []
        cursor = 0
        aligned: list[WordTiming] = []
        for source_token in source_tokens:
            normalized_source = _normalize_alignment_token(source_token)
            if not normalized_source:
                continue
            while cursor < len(normalized_transcribed) and normalized_transcribed[cursor][0] != normalized_source:
                cursor += 1
            if cursor >= len(normalized_transcribed):
                return []
            matched_word = normalized_transcribed[cursor][1]
            if matched_word.end <= matched_word.start:
                return []
            aligned.append(
                WordTiming(
                    start=matched_word.start,
                    end=matched_word.end,
                    text=source_token,
                )
            )
            cursor += 1
        return aligned


class MacOSTTSProvider(BaseTTSProvider):
    def _raw_suffix(self) -> str:
        return ".aiff"

    def _render_segment_audio(self, text: str, output_path: Path) -> None:
        rate_words_per_minute = max(90, round(175 * self.config.speech_speed))
        run_command(
            [
                "say",
                "-v",
                self.config.system_voice,
                "-r",
                str(rate_words_per_minute),
                "-o",
                str(output_path),
                text,
            ]
        )


class EspeakTTSProvider(BaseTTSProvider):
    def _raw_suffix(self) -> str:
        return ".wav"

    def _render_segment_audio(self, text: str, output_path: Path) -> None:
        rate_words_per_minute = max(120, round(175 * self.config.speech_speed))
        run_command(["espeak-ng", "-s", str(rate_words_per_minute), "-w", str(output_path), text])


class TonePlaceholderProvider(BaseTTSProvider):
    def _raw_suffix(self) -> str:
        return ".wav"

    def _render_segment_audio(self, text: str, output_path: Path) -> None:
        duration = max(1.1, min(len(text.split()) / 2.3, 4.0))
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={duration:.2f}",
                "-ar",
                str(self.config.sample_rate_hz),
                "-ac",
                "1",
                str(output_path),
            ]
        )


class ElevenLabsTTSProvider(BaseTTSProvider):
    def _render_segment_audio(self, text: str, output_path: Path) -> None:
        raise NotImplementedError("ElevenLabs handles word timings natively, use synthesize()")

    def synthesize(self, text: str, output_path: Path, *, segments: Sequence[StorySegment] | None = None) -> SynthesisResult:
        api_key = self.env.get(self.providers.elevenlabs_api_key_env, "").strip()
        if not api_key:
            raise ValueError(f"Missing ElevenLabs API key in {self.providers.elevenlabs_api_key_env}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        segment_list = list(segments or [StorySegment(stage="context", text=text, pause_after_ms=self.config.sentence_pause_ms)])
        with TemporaryDirectory(dir=output_path.parent) as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            concat_paths: list[Path] = []
            timed_segments: list[TranscriptSegment] = []
            cursor = 0.0

            for index, segment in enumerate(segment_list):
                raw_path = temp_dir / f"segment-{index}.mp3"
                normalized_path = temp_dir / f"segment-{index}-normalized.wav"
                previous_text = segment_list[index - 1].text if index > 0 else None
                next_text = segment_list[index + 1].text if index + 1 < len(segment_list) else None
                aligned_words = self._request_segment_with_timestamps(
                    segment.text,
                    raw_path,
                    api_key=api_key,
                    previous_text=previous_text,
                    next_text=next_text,
                )
                self._convert_to_wav(raw_path, normalized_path)
                duration = probe_duration(normalized_path)
                words = self._offset_word_timings(aligned_words, offset=cursor, duration=duration, text=segment.text)
                timed_segments.append(
                    TranscriptSegment(
                        start=cursor,
                        end=cursor + duration,
                        text=segment.text,
                        words=words,
                    )
                )
                cursor += duration
                concat_paths.append(normalized_path)
                if index < len(segment_list) - 1:
                    pause_ms = segment.pause_after_ms or self.config.sentence_pause_ms
                    if pause_ms > 0:
                        silence_path = temp_dir / f"pause-{index}.wav"
                        self._create_silence(pause_ms / 1000, silence_path)
                        concat_paths.append(silence_path)
                        cursor += pause_ms / 1000

            combined_path = temp_dir / "combined.wav"
            self._concat_wav_files(concat_paths, combined_path)
            self._normalize_audio(combined_path, output_path)
            return SynthesisResult(
                path=output_path,
                duration_seconds=probe_duration(output_path),
                segments=timed_segments,
            )

    def _request_segment_with_timestamps(
        self,
        text: str,
        output_path: Path,
        *,
        api_key: str,
        previous_text: str | None,
        next_text: str | None,
    ) -> list[WordTiming]:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.config.elevenlabs_voice_id}/with-timestamps"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {
            "text": text,
            "model_id": self.config.elevenlabs_model,
            "output_format": "mp3_44100_128",
        }
        payload["voice_settings"] = {"speed": self._elevenlabs_speed()}
        if previous_text:
            payload["previous_text"] = previous_text
        if next_text:
            payload["next_text"] = next_text

        response = requests.post(url, headers=headers, json=payload, timeout=self.providers.openai_timeout_seconds)
        response.raise_for_status()
        body = response.json()
        output_path.write_bytes(base64.b64decode(body["audio_base64"]))
        return self._align_segment_words(text, body.get("alignment", {}))

    def _align_segment_words(self, text: str, alignment: object) -> list[WordTiming]:
        if not isinstance(alignment, Mapping):
            return []
        raw_words = self._extract_alignment_words(alignment)
        if not raw_words:
            return []
        aligned_words = self._align_tokens_to_words(text.split(), raw_words)
        return aligned_words or raw_words

    def _extract_alignment_words(self, alignment: Mapping[str, object]) -> list[WordTiming]:
        chars = alignment.get("characters")
        starts = alignment.get("character_start_times_seconds")
        ends = alignment.get("character_end_times_seconds")
        if not isinstance(chars, list) or not isinstance(starts, list) or not isinstance(ends, list):
            return []
        if not chars or len(chars) != len(starts) or len(chars) != len(ends):
            return []

        words: list[WordTiming] = []
        current_word: list[str] = []
        current_start: float | None = None
        for index, char in enumerate(chars):
            if not isinstance(char, str):
                continue
            start = float(starts[index])
            end = float(ends[index])
            if char.isspace():
                if current_word and current_start is not None:
                    word_end = end if index == 0 else float(ends[index - 1])
                    words.append(
                        WordTiming(
                            start=current_start,
                            end=word_end,
                            text="".join(current_word),
                        )
                    )
                    current_word = []
                    current_start = None
                continue
            if current_start is None:
                current_start = start
            current_word.append(char)

        if current_word and current_start is not None:
            words.append(WordTiming(start=current_start, end=float(ends[-1]), text="".join(current_word)))
        return words

    def _align_tokens_to_words(
        self,
        source_tokens: Sequence[str],
        generated_words: Sequence[WordTiming],
    ) -> list[WordTiming]:
        normalized_generated = [
            (_normalize_alignment_token(word.text), word)
            for word in generated_words
            if _normalize_alignment_token(word.text)
        ]
        if len(normalized_generated) < len(source_tokens):
            return []
        cursor = 0
        aligned: list[WordTiming] = []
        for source_token in source_tokens:
            normalized_source = _normalize_alignment_token(source_token)
            if not normalized_source:
                continue
            while cursor < len(normalized_generated) and normalized_generated[cursor][0] != normalized_source:
                cursor += 1
            if cursor >= len(normalized_generated):
                return []
            matched_word = normalized_generated[cursor][1]
            aligned.append(WordTiming(start=matched_word.start, end=matched_word.end, text=source_token))
            cursor += 1
        return aligned

    def _offset_word_timings(
        self,
        words: Sequence[WordTiming],
        *,
        offset: float,
        duration: float,
        text: str,
    ) -> list[WordTiming]:
        if not words:
            return self._build_deterministic_word_timings(text, start=offset, end=offset + duration)
        offset_words = [
            WordTiming(
                start=offset + max(word.start, 0.0),
                end=offset + min(max(word.end, word.start + 0.03), duration),
                text=word.text,
            )
            for word in words
        ]
        if offset_words[-1].end < offset + duration:
            offset_words[-1] = offset_words[-1].model_copy(update={"end": offset + duration})
        return offset_words

    def _elevenlabs_speed(self) -> float:
        return max(0.7, min(self.config.speech_speed, 1.2))


def build_tts_provider(config: TTSConfig, providers: ProviderConfig, env: Mapping[str, str]) -> BaseTTSProvider:
    provider_name = config.provider.lower()

    if provider_name == "auto":
        if env.get(providers.elevenlabs_api_key_env, "").strip():
            return ElevenLabsTTSProvider(config, providers, env)
        if env.get(providers.openai_api_key_env, "").strip():
            return OpenAITTSProvider(config, providers, env)
        if _has_command("say"):
            return MacOSTTSProvider(config, providers, env)
        if _has_command("espeak-ng"):
            return EspeakTTSProvider(config, providers, env)
        return TonePlaceholderProvider(config, providers, env)

    if provider_name == "elevenlabs":
        return ElevenLabsTTSProvider(config, providers, env)
    if provider_name == "openai":
        return OpenAITTSProvider(config, providers, env)
    if provider_name == "macos":
        return MacOSTTSProvider(config, providers, env)
    if provider_name == "espeak":
        return EspeakTTSProvider(config, providers, env)
    return TonePlaceholderProvider(config, providers, env)
