from __future__ import annotations

from pathlib import Path

from tictoc_factory.media.gameplay import GameplayLibraryManager, GameplaySelector


def test_gameplay_library_plans_evenly_spaced_raw_clips(tmp_path: Path) -> None:
    manager = GameplayLibraryManager(
        gameplay_dir=tmp_path / "gameplay",
        raw_gameplay_dir=tmp_path / "gameplay_longform",
        work_dir=tmp_path / "work",
        target_lengths=[25, 35],
        clips_per_length=3,
        gameplay_speed=2.0,
    )
    source_path = tmp_path / "gameplay_longform" / "session.mp4"

    plans = manager.build_clip_plan(source_path=source_path, duration=120.0)

    assert len(plans) == 6
    assert plans[0].start == 0.0
    # At 2x speed, a 25s output clip needs 50s of raw footage
    assert plans[0].end == 50.0
    assert plans[1].target_duration == 25
    assert plans[-1].target_duration == 35
    assert plans[-1].end <= 120.0
    assert plans[-1].clip_path.parent == tmp_path / "gameplay"


def test_gameplay_library_skips_targets_longer_than_source(tmp_path: Path) -> None:
    manager = GameplayLibraryManager(
        gameplay_dir=tmp_path / "gameplay",
        raw_gameplay_dir=tmp_path / "gameplay_longform",
        work_dir=tmp_path / "work",
        target_lengths=[25, 35],
        clips_per_length=2,
        gameplay_speed=2.0,
    )
    source_path = tmp_path / "gameplay_longform" / "short.mp4"

    # At 2x speed, 25s output needs 50s raw → both 25 and 35 targets too long for 20s source
    plans = manager.build_clip_plan(source_path=source_path, duration=20.0)

    assert plans == []


def test_gameplay_selector_skips_unreadable_clips(tmp_path: Path, monkeypatch) -> None:
    selector = GameplaySelector(tmp_path)
    broken = tmp_path / "broken.mp4"
    valid = tmp_path / "valid.mp4"
    broken.write_text("not a real video")
    valid.write_text("placeholder")

    def fake_probe_duration(path: Path) -> float:
        if path == broken:
            raise RuntimeError("ffprobe failed")
        return 35.0

    monkeypatch.setattr("tictoc_factory.media.gameplay.probe_duration", fake_probe_duration)

    chosen = selector.select(30.0)

    assert chosen == valid
