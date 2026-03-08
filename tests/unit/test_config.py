from __future__ import annotations

from pathlib import Path

from tictoc_factory.config import load_settings


def test_load_settings_resolves_defaults(tmp_path: Path) -> None:
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    factory_config = configs_dir / "factory.local.yaml"
    accounts_config = configs_dir / "accounts.local.yaml"
    factory_config.write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits:
  - nosleep
  - TIFU
providers:
  llm_provider: openai
  tts_provider: elevenlabs
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [25, 35, 45]
content_policy:
  max_posts_per_day: 4
  min_source_score: 100
"""
    )
    accounts_config.write_text(
        """
accounts:
  - name: local-test
    enabled: true
    uploader: local_archive
    posting_windows:
      - "09:00-11:00"
      - "17:00-20:00"
    timezone: UTC
    template_tags: ["story"]
"""
    )

    settings = load_settings(factory_config, accounts_config, project_root=tmp_path)

    assert settings.mode == "reddit_story_gameplay"
    assert settings.default_subreddits == ["nosleep", "TIFU"]
    assert settings.providers.llm_provider == "openai"
    assert settings.providers.openai_model == "gpt-5-mini"
    assert settings.tts.provider == "elevenlabs"
    assert settings.tts.elevenlabs_voice_id == "pNInz6obpgDQGcFmaJgB"
    assert settings.tts.elevenlabs_model == "eleven_multilingual_v2"
    assert settings.tts.speech_speed == 1.16
    assert settings.tts.word_timing_mode == "auto"
    assert settings.subtitles.position_y == 0.50
    assert settings.story_pacing.target_duration_seconds_min == 30
    assert settings.paths.output_videos == tmp_path / "data" / "output" / "videos"
    assert settings.paths.gameplay_longform_input == tmp_path / "data" / "input" / "gameplay_longform"
    assert settings.accounts[0].name == "local-test"
    assert settings.accounts[0].posting_windows == ["09:00-11:00", "17:00-20:00"]


def test_load_settings_rejects_invalid_window(tmp_path: Path) -> None:
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    factory_config = configs_dir / "factory.local.yaml"
    accounts_config = configs_dir / "accounts.local.yaml"
    factory_config.write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits: [nosleep]
providers:
  llm_provider: openai
  tts_provider: espeak
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [30]
content_policy:
  max_posts_per_day: 4
  min_source_score: 100
"""
    )
    accounts_config.write_text(
        """
accounts:
  - name: local-test
    enabled: true
    uploader: local_archive
    posting_windows: ["soon"]
    timezone: UTC
    template_tags: ["story"]
"""
    )

    try:
        load_settings(factory_config, accounts_config, project_root=tmp_path)
    except ValueError as error:
        assert "posting window" in str(error).lower()
    else:
        raise AssertionError("Expected invalid window validation error")


def test_load_settings_supports_explicit_story_tuning_sections(tmp_path: Path) -> None:
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    factory_config = configs_dir / "factory.local.yaml"
    accounts_config = configs_dir / "accounts.local.yaml"
    factory_config.write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits: [nosleep]
providers:
  llm_provider: openai
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
tts:
  provider: auto
  openai_model: gpt-4o-mini-tts
  openai_voice: sage
  system_voice: Samantha
  speech_speed: 0.88
  sentence_pause_ms: 260
  word_timing_mode: deterministic
subtitles:
  font_size: 34
  max_words_per_line: 6
  max_lines_per_caption: 2
  position_y: 0.54
story_pacing:
  hook_max_words: 9
  target_duration_seconds_min: 32
  target_duration_seconds_max: 55
  suspense_segments: 10
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [30]
content_policy:
  max_posts_per_day: 4
  min_source_score: 100
"""
    )
    accounts_config.write_text(
        """
accounts:
  - name: local-test
    posting_windows: ["09:00-11:00"]
"""
    )

    settings = load_settings(factory_config, accounts_config, project_root=tmp_path)

    assert settings.tts.provider == "auto"
    assert settings.tts.openai_model == "gpt-4o-mini-tts"
    assert settings.tts.openai_voice == "sage"
    assert settings.tts.speech_speed == 0.88
    assert settings.tts.word_timing_mode == "deterministic"
    assert settings.subtitles.font_size == 34
    assert settings.subtitles.max_words_per_line == 6
    assert settings.subtitles.position_y == 0.54
    assert settings.story_pacing.hook_max_words == 9
    assert settings.story_pacing.target_duration_seconds_min == 32
    assert settings.story_pacing.suspense_segments == 10


def test_load_settings_backfills_legacy_word_timing_mode_from_subtitles(tmp_path: Path) -> None:
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    factory_config = configs_dir / "factory.local.yaml"
    accounts_config = configs_dir / "accounts.local.yaml"
    factory_config.write_text(
        """
project_name: tictoc-factory
mode: reddit_story_gameplay
default_subreddits: [nosleep]
providers:
  llm_provider: openai
  transcription_provider: sidecar
  openai_api_key_env: OPENAI_API_KEY
  openai_model: gpt-5-mini
  openai_timeout_seconds: 45
tts:
  provider: openai
subtitles:
  word_timing_mode: deterministic
scheduler:
  scan_interval_minutes: 15
  default_clip_lengths_seconds: [30]
content_policy:
  max_posts_per_day: 4
  min_source_score: 100
"""
    )
    accounts_config.write_text(
        """
accounts:
  - name: local-test
    posting_windows: ["09:00-11:00"]
"""
    )

    settings = load_settings(factory_config, accounts_config, project_root=tmp_path)

    assert settings.tts.word_timing_mode == "deterministic"
