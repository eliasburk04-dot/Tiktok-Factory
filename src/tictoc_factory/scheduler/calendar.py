from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..models import AccountConfig, QueueJob


class PostingScheduler:
    def next_slot(
        self,
        account: AccountConfig,
        *,
        now: datetime,
        scheduled_jobs: list[QueueJob],
    ) -> datetime:
        zone = ZoneInfo(account.timezone)
        localized_now = now.astimezone(zone)
        existing = [
            datetime.fromisoformat(job.scheduled_for).astimezone(zone)
            for job in scheduled_jobs
            if job.account_name == account.name and job.scheduled_for
        ]
        existing.sort()
        for day_offset in range(0, 7):
            current_day = (localized_now + timedelta(days=day_offset)).date()
            for window in account.posting_windows:
                start_text, end_text = window.split("-")
                start_hour, start_minute = [int(value) for value in start_text.split(":")]
                end_hour, end_minute = [int(value) for value in end_text.split(":")]
                start_dt = datetime.combine(current_day, time(start_hour, start_minute), tzinfo=zone)
                end_dt = datetime.combine(current_day, time(end_hour, end_minute), tzinfo=zone)
                candidate = self._window_candidate(
                    account_name=account.name,
                    current_day=current_day.isoformat(),
                    window=window,
                    start_dt=start_dt,
                    end_dt=end_dt,
                )
                candidate = max(candidate, start_dt).replace(second=0, microsecond=0)
                if candidate < localized_now:
                    candidate = localized_now.replace(second=0, microsecond=0)
                while candidate <= end_dt:
                    if all(
                        abs((candidate - item).total_seconds()) >= account.min_spacing_minutes * 60
                        for item in existing
                    ):
                        return candidate.astimezone(UTC)
                    candidate += timedelta(minutes=account.min_spacing_minutes)
        fallback = localized_now + timedelta(minutes=account.min_spacing_minutes)
        return fallback.astimezone(UTC)

    def _window_candidate(
        self,
        *,
        account_name: str,
        current_day: str,
        window: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> datetime:
        if end_dt <= start_dt:
            return start_dt
        total_minutes = int((end_dt - start_dt).total_seconds() // 60)
        digest = hashlib.sha256(f"{account_name}|{current_day}|{window}".encode()).digest()
        offset_minutes = int.from_bytes(digest[:4], "big") % (total_minutes + 1)
        return start_dt + timedelta(minutes=offset_minutes)
