"""Nextcloud WebDAV uploader.

Pushes finished videos into a Nextcloud folder so they sync to the
Nextcloud mobile app automatically.  Uses plain HTTP PUT via the
WebDAV endpoint — no extra SDK needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from ..models import QueueJob

logger = logging.getLogger(__name__)


class NextcloudUploader:
    """Upload videos to a Nextcloud instance via WebDAV.

    Parameters
    ----------
    base_url:
        The Nextcloud server URL, e.g. ``https://cloud.example.com``.
    username:
        Nextcloud login user.
    password:
        Nextcloud app-password (recommended) or regular password.
    remote_folder:
        Target folder inside the user's Nextcloud, e.g.
        ``/TikTok-Factory/ready``.  Created automatically if missing.
    """

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        remote_folder: str = "/TikTok-Factory/ready",
        timeout_seconds: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.remote_folder = remote_folder.strip("/")
        self.timeout = timeout_seconds
        self._webdav_root = f"{self.base_url}/remote.php/dav/files/{self.username}"

    # ── public interface (matches UploadProvider protocol) ───────────────
    def publish(self, job: QueueJob, video_path: Path) -> dict[str, str]:
        """Upload *video_path* into the configured Nextcloud folder."""
        self._ensure_folder_tree()
        remote_name = f"{job.job_id}.mp4"
        remote_url = f"{self._webdav_root}/{self.remote_folder}/{remote_name}"
        self._upload_file(video_path, remote_url)
        logger.info("Uploaded %s → %s", video_path.name, remote_url)
        return {
            "provider": "nextcloud",
            "remote_url": remote_url,
            "remote_folder": self.remote_folder,
            "status": "uploaded",
        }

    # ── internals ───────────────────────────────────────────────────────
    def _upload_file(self, local_path: Path, remote_url: str) -> None:
        with local_path.open("rb") as fh:
            resp = requests.put(
                remote_url,
                data=fh,
                auth=(self.username, self.password),
                headers={"Content-Type": "video/mp4"},
                timeout=self.timeout,
            )
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(
                f"Nextcloud upload failed ({resp.status_code}): {resp.text[:300]}"
            )

    def _ensure_folder_tree(self) -> None:
        """Create every segment of *remote_folder* via MKCOL."""
        parts = self.remote_folder.split("/")
        cumulative = ""
        for part in parts:
            if not part:
                continue
            cumulative = f"{cumulative}/{part}" if cumulative else part
            url = f"{self._webdav_root}/{cumulative}"
            resp = requests.request(
                "MKCOL",
                url,
                auth=(self.username, self.password),
                timeout=30,
            )
            # 201 = created, 405 = already exists — both fine
            if resp.status_code not in (201, 405):
                logger.debug("MKCOL %s → %s", url, resp.status_code)
