from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture()
def reddit_posts(fixture_dir: Path) -> list[dict[str, object]]:
    return json.loads((fixture_dir / "reddit_posts.json").read_text())


@pytest.fixture()
def podcast_segments(fixture_dir: Path) -> list[dict[str, object]]:
    return json.loads((fixture_dir / "podcast_segments.json").read_text())
