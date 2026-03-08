from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import QueueJob


class UploadProvider(Protocol):
    def publish(self, job: QueueJob, video_path: Path) -> dict[str, str]:
        """Publish or archive an artifact."""
        ...
