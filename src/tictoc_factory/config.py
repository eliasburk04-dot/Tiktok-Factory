from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

from .models import FactorySettings, PathConfig


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping config in {path}")
    return payload


def _build_paths(project_root: Path) -> PathConfig:
    data_root = project_root / "data"
    return PathConfig(
        root=project_root,
        src=project_root / "src",
        configs=project_root / "configs",
        gameplay_input=data_root / "input" / "gameplay",
        gameplay_longform_input=data_root / "input" / "gameplay_longform",
        longform_input=data_root / "input" / "longform" / "podcasts_streams",
        work=data_root / "work",
        output_videos=data_root / "output" / "videos",
        output_audio=data_root / "output" / "audio",
        output_subtitles=data_root / "output" / "subtitles",
        output_scripts=data_root / "output" / "scripts",
        analytics=data_root / "analytics",
        queue=data_root / "queue",
        queue_jobs=data_root / "queue" / "jobs",
        logs=project_root / "logs",
        bin_dir=project_root / "bin",
        tests=project_root / "tests",
    )


def load_settings(
    factory_config_path: Path,
    accounts_config_path: Path | None = None,
    *,
    project_root: Path | None = None,
    env_path: Path | None = None,
) -> FactorySettings:
    config_payload = _read_yaml(factory_config_path)
    accounts_payload = _read_yaml(accounts_config_path) if accounts_config_path else {}
    resolved_root = project_root or factory_config_path.resolve().parents[1]
    env_values = dict(dotenv_values(env_path)) if env_path and env_path.exists() else {}
    env_values.update({key: value for key, value in os.environ.items() if value})
    settings = FactorySettings.model_validate(
        {
            **config_payload,
            "accounts": accounts_payload.get("accounts", []),
            "paths": _build_paths(resolved_root),
            "env": env_values,
        }
    )
    settings.paths.ensure_directories()
    return settings
