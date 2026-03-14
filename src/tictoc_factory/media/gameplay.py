from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..utils.files import atomic_write_json, load_json
from ..utils.process import probe_duration, run_command
from ..utils.text import slugify


@dataclass(frozen=True)
class GameplayClipPlan:
    source_path: Path
    clip_path: Path
    start: float
    end: float
    target_duration: int


class GameplaySelector:
    def __init__(self, gameplay_dir: Path) -> None:
        self.gameplay_dir = gameplay_dir

    def select(self, target_duration: float) -> Path | None:
        candidates = sorted(self.gameplay_dir.glob("*.mp4"))
        if not candidates:
            return None
        best_path: Path | None = None
        best_delta = float("inf")
        for path in candidates:
            try:
                duration = probe_duration(path)
            except Exception:
                continue
            delta = abs(duration - target_duration)
            if duration >= target_duration and delta < best_delta:
                best_path = path
                best_delta = delta
        if best_path is not None:
            return best_path
        for path in candidates:
            try:
                probe_duration(path)
            except Exception:
                continue
            return path
        return None


class GameplayLibraryManager:
    def __init__(
        self,
        *,
        gameplay_dir: Path,
        raw_gameplay_dir: Path,
        work_dir: Path,
        target_lengths: list[int],
        clips_per_length: int = 3,
        gameplay_speed: float = 1.2,
        gameplay_target_fps: int = 30,
    ) -> None:
        self.gameplay_dir = gameplay_dir
        self.raw_gameplay_dir = raw_gameplay_dir
        self.work_dir = work_dir
        self.target_lengths = sorted(set(target_lengths))
        self.clips_per_length = clips_per_length
        self.gameplay_speed = max(gameplay_speed, 1.0)
        self.gameplay_target_fps = max(gameplay_target_fps, 1)
        self.manifest_path = self.work_dir / "gameplay_manifest.json"
        self.gameplay_dir.mkdir(parents=True, exist_ok=True)
        self.raw_gameplay_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def refresh_library(self) -> list[Path]:
        manifest = load_json(self.manifest_path, {"sources": {}})
        sources_manifest = manifest.setdefault("sources", {})
        created: list[Path] = []

        for source_path in sorted(self.raw_gameplay_dir.glob("*.mp4")):
            fingerprint = self._fingerprint(source_path)
            source_key = str(source_path)
            entry = sources_manifest.get(source_key, {})
            if entry.get("fingerprint") == fingerprint:
                existing_outputs = [Path(path) for path in entry.get("outputs", [])]
                if existing_outputs and all(path.exists() for path in existing_outputs):
                    continue

            previous_outputs = [Path(path) for path in entry.get("outputs", [])]
            for output_path in previous_outputs:
                if output_path.exists():
                    output_path.unlink()

            duration = probe_duration(source_path)
            plans = self.build_clip_plan(source_path=source_path, duration=duration)
            for plan in plans:
                if not plan.clip_path.exists():
                    self._extract_clip(plan)
                    created.append(plan.clip_path)

            sources_manifest[source_key] = {
                "fingerprint": fingerprint,
                "outputs": [str(plan.clip_path) for plan in plans],
            }

        atomic_write_json(self.manifest_path, manifest)
        return created

    def build_clip_plan(self, *, source_path: Path, duration: float) -> list[GameplayClipPlan]:
        plans: list[GameplayClipPlan] = []
        source_slug = slugify(source_path.stem)
        for target_duration in self.target_lengths:
            # We need (target_duration * speed) seconds of raw footage to produce
            # a target_duration-long clip after speed-up.
            raw_needed = target_duration * self.gameplay_speed
            if duration < raw_needed:
                continue
            latest_start = max(duration - raw_needed, 0.0)
            starts = self._start_positions(latest_start)
            for index, start in enumerate(starts, start=1):
                end = min(start + raw_needed, duration)
                clip_name = (
                    f"{source_slug}-{target_duration}s-{index:02d}-{int(start):04d}-{int(end):04d}.mp4"
                )
                plans.append(
                    GameplayClipPlan(
                        source_path=source_path,
                        clip_path=self.gameplay_dir / clip_name,
                        start=round(start, 2),
                        end=round(end, 2),
                        target_duration=target_duration,
                    )
                )
        return plans

    def _start_positions(self, latest_start: float) -> list[float]:
        if latest_start <= 0 or self.clips_per_length <= 1:
            return [0.0]
        if self.clips_per_length == 2:
            return [0.0, latest_start]
        step = latest_start / (self.clips_per_length - 1)
        return [round(step * index, 2) for index in range(self.clips_per_length)]

    def _extract_clip(self, plan: GameplayClipPlan) -> None:
        clip_duration = max(plan.end - plan.start, 1.0)
        # V4: Pre-accelerate gameplay during extraction so the composer does not
        # need a runtime setpts filter (which also caused the zoompan freeze bug).
        pts_factor = round(1.0 / self.gameplay_speed, 4)
        run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(plan.start),
                "-t",
                str(clip_duration),
                "-i",
                str(plan.source_path),
                "-filter:v",
                f"setpts={pts_factor}*PTS,fps={self.gameplay_target_fps}",
                "-an",
                "-c:v",
                "libx264",
                "-r",
                str(self.gameplay_target_fps),
                "-pix_fmt",
                "yuv420p",
                str(plan.clip_path),
            ]
        )

    def _fingerprint(self, path: Path) -> dict[str, object]:
        stat = path.stat()
        return {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "gameplay_speed": self.gameplay_speed,
            "gameplay_target_fps": self.gameplay_target_fps,
            "clips_per_length": self.clips_per_length,
            "target_lengths": self.target_lengths,
        }
