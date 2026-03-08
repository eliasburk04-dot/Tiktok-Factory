from __future__ import annotations

from datetime import UTC, datetime

from tictoc_factory.models import AccountConfig, QueueJob
from tictoc_factory.scheduler.calendar import PostingScheduler


def test_scheduler_assigns_next_slot_inside_account_window() -> None:
    scheduler = PostingScheduler()
    account = AccountConfig(
        name="local-test",
        enabled=True,
        uploader="local_archive",
        posting_windows=["09:00-11:00", "17:00-20:00"],
        timezone="UTC",
        template_tags=["story"],
    )
    now = datetime(2026, 3, 7, 8, 30, tzinfo=UTC)

    next_slot = scheduler.next_slot(account, now=now, scheduled_jobs=[])

    assert next_slot.hour == 9
    assert 0 <= next_slot.minute <= 59
    assert next_slot <= datetime(2026, 3, 7, 11, 0, tzinfo=UTC)


def test_scheduler_respects_existing_scheduled_jobs() -> None:
    scheduler = PostingScheduler()
    account = AccountConfig(
        name="local-test",
        enabled=True,
        uploader="local_archive",
        posting_windows=["09:00-10:00"],
        timezone="UTC",
        template_tags=["story"],
        min_spacing_minutes=30,
    )
    now = datetime(2026, 3, 7, 9, 5, tzinfo=UTC)
    scheduled = [
        QueueJob(
            job_id="job-1",
            mode="reddit_story_gameplay",
            source_type="reddit",
            state="scheduled",
            account_name="local-test",
            title="First",
            description="First job",
            created_at="2026-03-07T09:00:00+00:00",
            updated_at="2026-03-07T09:00:00+00:00",
            scheduled_for="2026-03-07T09:15:00+00:00",
            metadata={},
        )
    ]

    next_slot = scheduler.next_slot(account, now=now, scheduled_jobs=scheduled)

    assert next_slot.hour == 9
    assert next_slot.minute >= 45
    assert next_slot <= datetime(2026, 3, 7, 10, 0, tzinfo=UTC)


def test_scheduler_picks_deterministic_minute_within_window() -> None:
    scheduler = PostingScheduler()
    account = AccountConfig(
        name="local-test",
        enabled=True,
        uploader="local_archive",
        posting_windows=["16:50-17:10", "18:20-18:40", "19:50-20:10"],
        timezone="UTC",
        template_tags=["story"],
        min_spacing_minutes=60,
    )
    now = datetime(2026, 3, 7, 0, 0, tzinfo=UTC)

    first = scheduler.next_slot(account, now=now, scheduled_jobs=[])
    repeat = scheduler.next_slot(account, now=now, scheduled_jobs=[])

    assert first == repeat
    assert first.hour == 17
    assert 0 <= first.minute <= 10 or 50 <= first.minute <= 59
