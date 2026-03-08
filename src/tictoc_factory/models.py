from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ModeName = Literal["reddit_story_gameplay", "longform_clip", "hybrid"]
JobState = Literal[
    "discovered",
    "selected",
    "scripted",
    "audio_ready",
    "subtitles_ready",
    "composed",
    "scheduled",
    "published",
    "failed",
]


class ContentCandidate(BaseModel):
    id: str
    subreddit: str
    title: str
    body: str
    score: int = 0
    num_comments: int = 0
    created_utc: int
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ViralScoreResult(BaseModel):
    total: float
    normalized: float
    reasons: list[str]
    metrics: dict[str, float] = Field(default_factory=dict)


class HookOutput(BaseModel):
    template_id: str
    text: str
    style_tag: str


StoryStage = Literal["hook", "context", "escalation", "disturbing_detail", "final_twist", "cta"]
WordTimingMode = Literal["auto", "transcription", "deterministic"]


class StorySegment(BaseModel):
    stage: StoryStage
    text: str
    pause_after_ms: int = 0


class ScriptArtifact(BaseModel):
    hook: str
    setup: str
    tension: str
    payoff: str
    cta: str
    narration: str
    summary: str
    segments: list[StorySegment] = Field(default_factory=list)


class WordTiming(BaseModel):
    start: float
    end: float
    text: str

    @field_validator("end")
    @classmethod
    def validate_word_end(cls, value: float, info: Any) -> float:
        start = info.data.get("start", 0.0)
        if value <= start:
            raise ValueError("Word timing end must be greater than start")
        return value


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    words: list[WordTiming] = Field(default_factory=list)

    @field_validator("end")
    @classmethod
    def validate_end(cls, value: float, info: Any) -> float:
        start = info.data.get("start", 0.0)
        if value <= start:
            raise ValueError("Transcript segment end must be greater than start")
        return value

    @property
    def duration(self) -> float:
        return self.end - self.start


class ClipCandidate(BaseModel):
    start: float
    end: float
    score: float
    summary: str
    transcript_excerpt: str
    reasons: list[str]
    source_path: Path | None = None


class ProviderConfig(BaseModel):
    discovery_provider: str = "reddit"
    llm_provider: str = "openai"
    tts_provider: str = "elevenlabs"
    transcription_provider: str = "sidecar"
    openai_api_key_env: str = "OPENAI_API_KEY"
    elevenlabs_api_key_env: str = "ELEVENLABS_API_KEY"
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: int = 45


class SchedulerConfig(BaseModel):
    scan_interval_minutes: int = 15
    default_clip_lengths_seconds: list[int] = Field(default_factory=lambda: [25, 35, 45])


class TTSConfig(BaseModel):
    provider: str = "auto"
    openai_model: str = "gpt-4o-mini-tts"
    openai_voice: str = "nova"
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"
    system_voice: str = "Samantha"
    sample_rate_hz: int = 44_100
    speech_speed: float = 1.16
    sentence_pause_ms: int = 140
    normalize_lufs: float = -16.0
    word_timing_mode: WordTimingMode = "auto"
    openai_instructions: str = (
        "You are an expressive, emotional storyteller narrating a shocking true story from Reddit. "
        "Speak very naturally, with varied intonation, wide emotional range, and a sense of breathless urgency. "
        "Sound genuinely surprised or shocked where appropriate. "
        "Do not sound robotic, calm, or like a traditional audiobook. "
        "Keep the pace fast and energetic."
    )

    @field_validator("sample_rate_hz")
    @classmethod
    def validate_sample_rate(cls, value: int) -> int:
        if value < 44_100:
            raise ValueError("TTS sample rate must be at least 44100Hz")
        return value

    @field_validator("speech_speed")
    @classmethod
    def validate_speech_speed(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("speech_speed must be greater than zero")
        return value


class SubtitleConfig(BaseModel):
    font_name: str = "Montserrat Black"
    font_file: str = "/opt/tictoc-factory/fonts/Montserrat-Black.ttf"
    font_size: int = 56
    max_words_per_line: int = 3
    max_lines_per_caption: int = 2
    margin_horizontal: int = 120
    position_y: float = 0.50
    outline: int = 8
    shadow: int = 3
    stroke_color: str = "#000000"
    shadow_color: str = "#000000CC"
    highlight_color: str = "#00e5ff"
    active_word_scale: float = 1.18
    pop_animation_strength: float = 0.18
    pop_animation_ms: int = 80

    @field_validator("position_y")
    @classmethod
    def validate_position_y(cls, value: float) -> float:
        if value <= 0 or value >= 1:
            raise ValueError("subtitle position_y must be between 0 and 1")
        return value

    @field_validator("active_word_scale")
    @classmethod
    def validate_active_word_scale(cls, value: float) -> float:
        if value < 1:
            raise ValueError("active_word_scale must be at least 1")
        return value

    @field_validator("pop_animation_strength")
    @classmethod
    def validate_pop_animation_strength(cls, value: float) -> float:
        if value < 0:
            raise ValueError("pop_animation_strength must be zero or greater")
        return value

    @field_validator("pop_animation_ms")
    @classmethod
    def validate_pop_animation_ms(cls, value: int) -> int:
        if value < 0:
            raise ValueError("pop_animation_ms must be zero or greater")
        return value


class StoryPacingConfig(BaseModel):
    hook_max_words: int = 8
    max_segment_words: int = 12
    suspense_segments: int = 9
    minimum_total_words: int = 60
    target_duration_seconds_min: int = 30
    target_duration_seconds_max: int = 60
    intro_pause_ms: int = 180
    mid_pause_ms: int = 140
    final_pause_ms: int = 90


class RedditCardConfig(BaseModel):
    enabled: bool = True
    duration_seconds: float = 2.5
    card_width: int = 930
    position_y: float = 0.5
    corner_radius: int = 30
    title_font_size: int = 38
    body_font_size: int = 28
    meta_font_size: int = 22
    max_body_lines: int = 7
    background_color: str = "#171b22"
    border_color: str = "#2d333b"
    meta_color: str = "#c9d1d9"
    secondary_color: str = "#8b949e"
    accent_color: str = "#ff4500"

    @field_validator("duration_seconds")
    @classmethod
    def validate_duration(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("reddit card duration must be greater than zero")
        return value

    @field_validator("position_y")
    @classmethod
    def validate_card_position_y(cls, value: float) -> float:
        if value <= 0 or value >= 1:
            raise ValueError("reddit card position_y must be between 0 and 1")
        return value


class ContentPolicyConfig(BaseModel):
    max_posts_per_day: int = 3
    min_source_score: int = 1500
    preferred_modes: list[ModeName] = Field(default_factory=lambda: ["reddit_story_gameplay"])


class CompositionConfig(BaseModel):
    layout: Literal["split", "fullscreen"] = "split"
    subtitles_style: str = "bold_box"
    width: int = 1080
    height: int = 1920
    font_file: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class AccountConfig(BaseModel):
    name: str
    enabled: bool = True
    uploader: str = "local_archive"
    posting_windows: list[str]
    timezone: str = "UTC"
    template_tags: list[str] = Field(default_factory=lambda: ["story"])
    min_spacing_minutes: int = 30

    @field_validator("posting_windows")
    @classmethod
    def validate_windows(cls, value: list[str]) -> list[str]:
        for item in value:
            if len(item) != 11 or item[2] != ":" or item[5] != "-" or item[8] != ":":
                raise ValueError(f"Invalid posting window: {item}")
        return value


class PathConfig(BaseModel):
    root: Path
    src: Path
    configs: Path
    gameplay_input: Path
    gameplay_longform_input: Path
    longform_input: Path
    work: Path
    output_videos: Path
    output_audio: Path
    output_subtitles: Path
    output_scripts: Path
    analytics: Path
    queue: Path
    queue_jobs: Path
    logs: Path
    bin_dir: Path
    tests: Path

    def ensure_directories(self) -> None:
        for path in [
            self.root,
            self.src,
            self.configs,
            self.gameplay_input,
            self.gameplay_longform_input,
            self.longform_input,
            self.work,
            self.output_videos,
            self.output_audio,
            self.output_subtitles,
            self.output_scripts,
            self.analytics,
            self.queue,
            self.queue_jobs,
            self.logs,
            self.bin_dir,
            self.tests,
        ]:
            path.mkdir(parents=True, exist_ok=True)


class FactorySettings(BaseModel):
    project_name: str
    mode: ModeName
    default_subreddits: list[str]
    providers: ProviderConfig
    tts: TTSConfig = Field(default_factory=TTSConfig)
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    story_pacing: StoryPacingConfig = Field(default_factory=StoryPacingConfig)
    reddit_card: RedditCardConfig = Field(default_factory=RedditCardConfig)
    scheduler: SchedulerConfig
    content_policy: ContentPolicyConfig
    composition: CompositionConfig = Field(default_factory=CompositionConfig)
    paths: PathConfig
    accounts: list[AccountConfig]
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def backfill_legacy_sections(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        providers = values.get("providers", {}) or {}
        composition = values.get("composition", {}) or {}
        tts_config = dict(values.get("tts", {}) or {})
        subtitles_config = dict(values.get("subtitles", {}) or {})
        legacy_word_timing_mode = subtitles_config.pop("word_timing_mode", None)

        if "provider" not in tts_config and providers.get("tts_provider"):
            tts_config["provider"] = providers["tts_provider"]
        if "font_file" not in subtitles_config and composition.get("font_file"):
            subtitles_config["font_file"] = composition["font_file"]
        if "word_timing_mode" not in tts_config and legacy_word_timing_mode:
            tts_config["word_timing_mode"] = legacy_word_timing_mode

        values["tts"] = tts_config
        values["subtitles"] = subtitles_config
        return values


class QueueJob(BaseModel):
    job_id: str
    mode: ModeName
    source_type: str
    state: JobState
    account_name: str | None = None
    title: str
    description: str
    created_at: str
    updated_at: str
    scheduled_for: str | None = None
    source_path: str | None = None
    output_video_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self, state: JobState, now: datetime) -> QueueJob:
        return self.model_copy(update={"state": state, "updated_at": now.isoformat()})
