from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..analytics.store import AnalyticsStore
from ..audio.providers import build_tts_provider
from ..config import FactorySettings
from ..discovery.fixture import FixtureDiscoveryProvider
from ..discovery.reddit import RedditDiscoveryProvider
from ..hooks.generator import HookGenerator
from ..llm.creative import build_openai_creative_director
from ..media.clip_miner import ClipMiner
from ..media.composer import VideoComposer
from ..media.gameplay import GameplayLibraryManager, GameplaySelector
from ..media.splitter import VideoPart, split_video
from ..models import (
    AccountConfig,
    ClipCandidate,
    ContentCandidate,
    HookOutput,
    ModeName,
    QueueJob,
    ScriptArtifact,
    TranscriptSegment,
)
from ..predictor import PrePublishPredictor
from ..scheduler.calendar import PostingScheduler
from ..scheduler.queue import QueueStore
from ..scoring import ViralScoreCalculator
from ..script_builder import StoryScriptBuilder
from ..subtitles.generator import SubtitleGenerator
from ..uploaders.local_archive import LocalArchiveUploader
from ..uploaders.nextcloud import NextcloudUploader
from ..utils.files import atomic_write_json
from ..utils.logging import StructuredLogger
from ..utils.process import probe_duration
from ..utils.text import slugify


@dataclass
class PipelineRunResult:
    discovered_jobs: int
    processed_jobs: int
    scheduled_jobs: int


class FactoryPipeline:
    def __init__(self, settings: FactorySettings) -> None:
        self.settings = settings
        self.queue = QueueStore(settings.paths.queue_jobs)
        self.analytics = AnalyticsStore(settings.paths.analytics)
        self.scorer = ViralScoreCalculator()
        self.hooks = HookGenerator()
        self.script_builder = StoryScriptBuilder(settings.story_pacing)
        self.predictor = PrePublishPredictor()
        self.clip_miner = ClipMiner(settings.scheduler.default_clip_lengths_seconds)
        self.tts_provider = build_tts_provider(settings.tts, settings.providers, settings.env)
        self.subtitles = SubtitleGenerator(settings.subtitles, settings.composition)
        self.gameplay = GameplaySelector(settings.paths.gameplay_input)
        self.gameplay_library = GameplayLibraryManager(
            gameplay_dir=settings.paths.gameplay_input,
            raw_gameplay_dir=settings.paths.gameplay_longform_input,
            work_dir=settings.paths.work,
            target_lengths=settings.scheduler.default_clip_lengths_seconds,
            gameplay_target_fps=settings.composition.gameplay_target_fps,
        )
        self.composer = VideoComposer(settings.composition, settings.subtitles, settings.reddit_card, settings.paths.work)
        self.scheduler = PostingScheduler()
        published_root = settings.paths.output_videos.parent / "published"
        self.uploader = LocalArchiveUploader(published_root)
        self.nextcloud: NextcloudUploader | None = None
        if settings.nextcloud.enabled and settings.nextcloud.base_url:
            nc_password = settings.env.get(settings.nextcloud.password_env, "")
            if nc_password:
                self.nextcloud = NextcloudUploader(
                    base_url=settings.nextcloud.base_url,
                    username=settings.nextcloud.username,
                    password=nc_password,
                    remote_folder=settings.nextcloud.remote_folder,
                    timeout_seconds=settings.nextcloud.timeout_seconds,
                )
        self.logger = StructuredLogger(settings.paths.logs / "factory.jsonl")
        self.creative_director = build_openai_creative_director(
            api_key=settings.env.get(settings.providers.openai_api_key_env),
            model=settings.providers.openai_model,
            timeout_seconds=settings.providers.openai_timeout_seconds,
        )

    def run_cycle(self, *, now_iso: str | None = None) -> PipelineRunResult:
        now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
        self._refresh_gameplay_library()
        discovered_jobs = self._discover_jobs(now)
        processed = 0
        remaining_capacity = self._remaining_daily_capacity(now)
        retryable_jobs = []
        for job in self.queue.list_jobs():
            attempts = int(job.metadata.get("attempts", 0))
            if job.state in {"discovered", "selected", "scripted", "audio_ready", "subtitles_ready"} or (
                job.state == "failed" and attempts < 2
            ):
                retryable_jobs.append(job)
        retryable_jobs.sort(
            key=lambda job: float(job.metadata.get("score", {}).get("total", 0.0)),
            reverse=True,
        )
        for job in retryable_jobs[:remaining_capacity]:
            self._process_job(job, now)
            processed += 1
        scheduled = len(self.queue.find_by_state("scheduled", "published"))
        return PipelineRunResult(discovered_jobs=discovered_jobs, processed_jobs=processed, scheduled_jobs=scheduled)

    def _refresh_gameplay_library(self) -> None:
        try:
            created_clips = self.gameplay_library.refresh_library()
        except Exception as error:
            self.analytics.record_event("gameplay_refresh_failure", {"error": str(error)})
            self.logger.error("gameplay_refresh_failure", error=str(error))
            return
        if not created_clips:
            return
        self.analytics.record_event("gameplay_refresh", {"created_clips": len(created_clips)})
        self.logger.info("gameplay_refresh", created_clips=len(created_clips))

    def _remaining_daily_capacity(self, now: datetime) -> int:
        enabled_accounts = [account for account in self.settings.accounts if account.enabled]
        if not enabled_accounts:
            return self.settings.content_policy.max_posts_per_day

        account = enabled_accounts[0]
        zone = ZoneInfo(account.timezone)
        local_day = now.astimezone(zone).date()
        scheduled_today = 0
        for job in self.queue.list_jobs():
            if job.account_name != account.name or not job.scheduled_for:
                continue
            scheduled_day = datetime.fromisoformat(job.scheduled_for).astimezone(zone).date()
            if scheduled_day == local_day and job.state in {"scheduled", "published"}:
                scheduled_today += 1
        return max(self.settings.content_policy.max_posts_per_day - scheduled_today, 0)

    def publish_due(self, *, now_iso: str | None = None) -> int:
        now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
        published = 0
        for job in self.queue.find_by_state("scheduled"):
            if not job.scheduled_for or datetime.fromisoformat(job.scheduled_for) > now:
                continue
            if not job.output_video_path:
                continue
            receipt = self.uploader.publish(job, Path(job.output_video_path))
            job = job.model_copy(
                update={
                    "state": "published",
                    "updated_at": now.isoformat(),
                    "metadata": {**job.metadata, "publish_receipt": receipt},
                }
            )
            self.queue.upsert(job)
            self.analytics.record_event("publish", {"job_id": job.job_id, "account": job.account_name, **receipt})
            published += 1
        return published

    def regenerate_batch(self, *, now_iso: str | None = None) -> PipelineRunResult:
        self._purge_generated_artifacts()
        return self.run_cycle(now_iso=now_iso)

    def _discover_jobs(self, now: datetime) -> int:
        existing = {job.job_id for job in self.queue.list_jobs()}
        created = 0
        if self.settings.mode in {"reddit_story_gameplay", "hybrid"}:
            try:
                reddit_candidates = self._discover_reddit_candidates()
            except Exception as error:
                self.analytics.record_event("discovery_failure", {"source": "reddit", "error": str(error)})
                self.logger.error("discovery_failure", source="reddit", error=str(error))
                reddit_candidates = []
            duration_ready_candidates = [
                candidate
                for candidate in reddit_candidates
                if self.script_builder.supports_target_duration(candidate, mode="reddit_story_gameplay")
            ]
            reddit_candidates = duration_ready_candidates
            for candidate in reddit_candidates:
                # V4: Filter by raw Reddit score (upvotes) directly instead of
                # the internal viral-score metric to ensure we only pick
                # genuinely popular, high-quality stories.
                if candidate.score < self.settings.content_policy.min_source_score:
                    continue
                score = self.scorer.score_candidate(candidate)
                job_id = f"reddit-{candidate.id}-{slugify(candidate.title)[:32]}"
                if job_id in existing:
                    continue
                job = QueueJob(
                    job_id=job_id,
                    mode="reddit_story_gameplay",
                    source_type="reddit",
                    state="discovered",
                    title=candidate.title,
                    description=candidate.body,
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                    metadata={"candidate": candidate.model_dump(mode="json"), "score": score.model_dump(mode="json")},
                )
                self.queue.upsert(job)
                self.analytics.record_event("discover_reddit", {"job_id": job_id, "title": candidate.title})
                self.logger.info("discover_reddit", job_id=job_id, title=candidate.title)
                existing.add(job_id)
                created += 1
        if self.settings.mode in {"longform_clip", "hybrid"}:
            for media_path in sorted(self.settings.paths.longform_input.glob("*.mp4")):
                try:
                    job = self._build_longform_job(media_path, now)
                except Exception as error:
                    self.analytics.record_event(
                        "discovery_failure",
                        {"source": str(media_path), "error": str(error)},
                    )
                    self.logger.error("discovery_failure", source=str(media_path), error=str(error))
                    job = None
                if not job or job.job_id in existing:
                    continue
                self.queue.upsert(job)
                self.analytics.record_event("discover_longform", {"job_id": job.job_id, "source": str(media_path)})
                self.logger.info("discover_longform", job_id=job.job_id, source=str(media_path))
                existing.add(job.job_id)
                created += 1
        return created

    def _discover_reddit_candidates(self) -> list[ContentCandidate]:
        provider_name = self.settings.providers.discovery_provider
        if provider_name == "fixture":
            provider = FixtureDiscoveryProvider(self.settings.paths.root / "data" / "input" / "reddit_fixture.json")
        else:
            provider = RedditDiscoveryProvider()
        candidates = provider.fetch_candidates(self.settings.default_subreddits)
        candidates.sort(key=lambda item: self.scorer.score_candidate(item).total, reverse=True)
        return candidates[: self.settings.content_policy.max_posts_per_day]

    def _build_longform_job(self, media_path: Path, now: datetime) -> QueueJob | None:
        segments = self.clip_miner.load_sidecar_segments(media_path)
        silence_intervals = self.clip_miner.detect_silence(media_path)
        ranked = self.clip_miner.rank_segments(
            media_path=media_path,
            transcript_segments=segments,
            silence_intervals=silence_intervals,
            top_k=3,
        )
        if not ranked:
            return None
        clip = ranked[0]
        if self.creative_director and segments:
            try:
                clip = self.creative_director.rerank_clips(
                    candidate=self._longform_candidate_seed(media_path, ranked[0], now),
                    clips=ranked,
                )
            except Exception as error:
                self.analytics.record_event(
                    "openai_rerank_failure",
                    {"source": str(media_path), "error": str(error)},
                )
                self.logger.error("openai_rerank_failure", source=str(media_path), error=str(error))
        candidate = self._longform_candidate_seed(media_path, clip, now)
        score = self.scorer.score_candidate(candidate)
        return QueueJob(
            job_id=f"longform-{slugify(media_path.stem)}-{int(clip.start)}-{int(clip.end)}",
            mode="hybrid" if self.settings.mode == "hybrid" else "longform_clip",
            source_type="longform",
            state="discovered",
            title=candidate.title,
            description=clip.summary,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            source_path=str(media_path),
            metadata={
                "candidate": candidate.model_dump(mode="json"),
                "clip": clip.model_dump(mode="json"),
                "transcript_segments": [item.model_dump(mode="json") for item in segments],
                "score": score.model_dump(mode="json"),
            },
        )

    def _longform_candidate_seed(self, media_path: Path, clip: ClipCandidate, now: datetime) -> ContentCandidate:
        return ContentCandidate(
            id=media_path.stem,
            subreddit="longform",
            title=f"Clip from {media_path.stem}",
            body=clip.summary,
            score=int(clip.score * 1000),
            num_comments=0,
            created_utc=int(now.timestamp()),
            metadata={"source_path": str(media_path)},
        )

    def _process_job(self, job: QueueJob, now: datetime) -> None:
        try:
            candidate = ContentCandidate.model_validate(job.metadata["candidate"])
            clip = ClipCandidate.model_validate(job.metadata["clip"]) if "clip" in job.metadata else None
            hook, script, creative_metadata = self._generate_creative_package(candidate=candidate, mode=job.mode, clip=clip)
            script_path = self.settings.paths.output_scripts / f"{job.job_id}.json"
            atomic_write_json(script_path, script.model_dump(mode="json"))
            self.analytics.register_template_use(hook.template_id)
            processed_job = job.touch("scripted", now)
            processed_job.metadata.update(
                {
                    "hook": hook.model_dump(mode="json"),
                    "script": script.model_dump(mode="json"),
                    "creative": creative_metadata,
                }
            )

            audio_path = None
            subtitle_path = self.settings.paths.output_subtitles / f"{job.job_id}.srt"
            if job.source_type == "reddit":
                audio_path = self.settings.paths.output_audio / f"{job.job_id}.wav"
                subtitle_path = self.settings.paths.output_subtitles / f"{job.job_id}.ass"
                synthesis = self.tts_provider.synthesize(script.narration, audio_path, segments=script.segments)
                self.subtitles.generate_from_script(script, output_path=subtitle_path, segment_timings=synthesis.segments)
                processed_job.metadata.update(
                    {
                        "audio_path": str(audio_path),
                        "audio_duration_seconds": synthesis.duration_seconds,
                        "subtitles_path": str(subtitle_path),
                    }
                )
            else:
                real_segments = [
                    TranscriptSegment.model_validate(item)
                    for item in processed_job.metadata.get("transcript_segments", [])
                ]
                clip_candidate = clip or ClipCandidate(
                    start=0.0,
                    end=probe_duration(Path(processed_job.source_path or "")),
                    score=1.0,
                    summary=script.summary,
                    transcript_excerpt=script.summary,
                    reasons=[],
                )
                self.subtitles.generate_from_segments(
                    real_segments,
                    clip_start=clip_candidate.start,
                    clip_end=clip_candidate.end,
                    output_path=subtitle_path,
                )
                processed_job.metadata.update({"subtitles_path": str(subtitle_path)})
            processed_job = processed_job.touch("subtitles_ready", now)

            output_video_path = self.settings.paths.output_videos / f"{job.job_id}.mp4"
            if job.source_type == "reddit":
                self._compose_story_job(
                    processed_job,
                    candidate,
                    audio_path,
                    subtitle_path,
                    output_video_path,
                )
            else:
                self._compose_longform_job(processed_job, clip, subtitle_path, output_video_path)

            # ── Split long videos into parts ────────────────────────────
            kinetic_path = subtitle_path.with_suffix(".kinetic.json") if subtitle_path else None
            min_dur = float(self.settings.content_policy.min_video_duration_seconds)
            max_dur = float(self.settings.content_policy.max_video_duration_seconds)
            parts = split_video(
                output_video_path,
                kinetic_path,
                self.settings.paths.output_videos,
                min_duration=min_dur,
                max_duration=max_dur,
                job_id=job.job_id,
            )

            score_payload = self.predictor.predict(
                script=script,
                source_score=self.scorer.score_candidate(candidate),
                clip=clip,
            )
            account = self._select_account()

            # ── Schedule each part into consecutive posting slots ────────
            for part in parts:
                part_job_id = f"{job.job_id}-part{part.part_number}" if part.total_parts > 1 else job.job_id
                part_video_path = part.output_path

                scheduled_at = self.scheduler.next_slot(account, now=now, scheduled_jobs=self.queue.list_jobs())
                part_title = job.title
                if part.total_parts > 1:
                    part_title = f"{job.title} (Part {part.part_number}/{part.total_parts})"

                part_metadata = {
                    **processed_job.metadata,
                    "attempts": int(job.metadata.get("attempts", 0)),
                    "pre_publish": score_payload,
                    "script_path": str(script_path),
                    "output_video_path": str(part_video_path),
                    "part_number": part.part_number,
                    "total_parts": part.total_parts,
                    "part_start_seconds": part.start_seconds,
                    "part_end_seconds": part.end_seconds,
                }

                scheduled_job = QueueJob(
                    job_id=part_job_id,
                    mode=job.mode,
                    source_type=job.source_type,
                    state="scheduled",
                    account_name=account.name,
                    title=part_title,
                    description=job.description,
                    created_at=job.created_at,
                    updated_at=now.isoformat(),
                    scheduled_for=scheduled_at.isoformat(),
                    source_path=job.source_path,
                    output_video_path=str(part_video_path),
                    metadata=part_metadata,
                )
                self.queue.upsert(scheduled_job)

                # ── Upload to Nextcloud ─────────────────────────────────
                if self.nextcloud:
                    try:
                        nc_receipt = self.nextcloud.publish(scheduled_job, part_video_path)
                        scheduled_job.metadata["nextcloud"] = nc_receipt
                        self.queue.upsert(scheduled_job)
                        self.logger.info(
                            "nextcloud_upload",
                            job_id=part_job_id,
                            remote_url=nc_receipt.get("remote_url", ""),
                        )
                    except Exception as nc_err:
                        self.logger.error("nextcloud_upload_failed", job_id=part_job_id, error=str(nc_err))

                self.analytics.record_event(
                    "schedule",
                    {
                        "job_id": part_job_id,
                        "account": account.name,
                        "scheduled_for": scheduled_job.scheduled_for,
                        "pre_publish_score": score_payload["score"],
                        "part": f"{part.part_number}/{part.total_parts}",
                    },
                )
                self.logger.info(
                    "schedule",
                    job_id=part_job_id,
                    account=account.name,
                    scheduled_for=scheduled_job.scheduled_for,
                    part=f"{part.part_number}/{part.total_parts}",
                )

            # If we created part-jobs, remove the original parent job
            if parts and parts[0].total_parts > 1:
                original_path = self.settings.paths.queue_jobs / f"{job.job_id}.json"
                if original_path.exists():
                    original_path.unlink()

        except Exception as error:
            attempts = int(job.metadata.get("attempts", 0)) + 1
            failed_job = job.model_copy(
                update={
                    "state": "failed",
                    "updated_at": now.isoformat(),
                    "metadata": {
                        **job.metadata,
                        "attempts": attempts,
                        "last_error": str(error),
                    },
                }
            )
            self.queue.upsert(failed_job)
            self.analytics.record_event("failure", {"job_id": job.job_id, "error": str(error), "attempts": attempts})
            self.logger.error("failure", job_id=job.job_id, error=str(error), attempts=attempts)

    def _generate_creative_package(
        self,
        *,
        candidate: ContentCandidate,
        mode: ModeName,
        clip: ClipCandidate | None,
    ) -> tuple[HookOutput, ScriptArtifact, dict[str, str]]:
        # V4: For reddit_story_gameplay we NEVER let the LLM rewrite the story.
        # The original Reddit text must be spoken verbatim.
        if mode == "reddit_story_gameplay":
            recent_templates = self.analytics.recent_template_ids()
            hook = self.hooks.generate(candidate, recent_template_ids=recent_templates)
            script = self.script_builder.build(candidate, hook, mode=mode, clip=clip)
            metadata: dict[str, str] = {"provider": "verbatim", "model": "n/a"}
            return hook, script, metadata

        creative_hook: HookOutput | None = None
        creative_metadata: dict[str, str] | None = None
        if self.creative_director is not None:
            try:
                creative_hook, creative_script, creative_metadata = self.creative_director.generate_story_package(
                    candidate=candidate,
                    mode=mode,
                    clip=clip,
                )
                return creative_hook, creative_script, creative_metadata
            except Exception as error:
                self.analytics.record_event(
                    "openai_creative_failure",
                    {"candidate_id": candidate.id, "error": str(error)},
                )
                self.logger.error("openai_creative_failure", candidate_id=candidate.id, error=str(error))

        if creative_hook is None:
            recent_templates = self.analytics.recent_template_ids()
            hook = self.hooks.generate(candidate, recent_template_ids=recent_templates)
            metadata = {"provider": "local_heuristic", "model": "n/a"}
        else:
            hook = creative_hook
            metadata = creative_metadata or {"provider": "openai", "model": "unknown"}
        script = self.script_builder.build(candidate, hook, mode=mode, clip=clip)
        return hook, script, metadata

    def _compose_story_job(
        self,
        job: QueueJob,
        candidate: ContentCandidate,
        audio_path: Path | None,
        subtitle_path: Path,
        output_video_path: Path,
    ) -> None:
        if audio_path is None:
            raise ValueError("Story jobs require synthesized audio")
        duration = probe_duration(audio_path)
        gameplay = self.gameplay.select(duration)
        if gameplay is None:
            raise FileNotFoundError("No gameplay clips available in data/input/gameplay")
        intro_card_path: Path | None = None
        if self.settings.reddit_card.enabled:
            intro_card_path = self.settings.paths.work / f"{job.job_id}-post-card.png"
            self.composer.render_reddit_post_card(candidate, intro_card_path)
        self.composer.compose_story_gameplay(
            gameplay_path=gameplay,
            subtitles_path=subtitle_path,
            audio_path=audio_path,
            intro_card_path=intro_card_path,
            output_path=output_video_path,
        )

    def _compose_longform_job(
        self,
        job: QueueJob,
        clip: ClipCandidate | None,
        subtitle_path: Path,
        output_video_path: Path,
    ) -> None:
        source_path = Path(job.source_path or "")
        if not source_path.exists():
            raise FileNotFoundError(f"Missing longform source: {source_path}")
        clip_candidate = clip or ClipCandidate(
            start=0.0,
            end=probe_duration(source_path),
            score=1.0,
            summary=job.description,
            transcript_excerpt=job.description,
            reasons=[],
        )
        extracted_path = self.settings.paths.work / f"{job.job_id}-clip.mp4"
        self.composer.extract_clip(source_path, clip_candidate.start, clip_candidate.end, extracted_path)
        gameplay = self.gameplay.select(clip_candidate.end - clip_candidate.start)
        if job.mode == "hybrid" and gameplay is not None:
            self.composer.compose_hybrid(
                clip_path=extracted_path,
                gameplay_path=gameplay,
                subtitles_path=subtitle_path,
                output_path=output_video_path,
            )
            return
        self.composer.compose_longform_clip(
            clip_path=extracted_path,
            subtitles_path=subtitle_path,
            output_path=output_video_path,
        )

    def _select_account(self) -> AccountConfig:
        enabled = [account for account in self.settings.accounts if account.enabled]
        if not enabled:
            raise ValueError("No enabled accounts configured")
        return enabled[0]

    def _purge_generated_artifacts(self) -> None:
        for directory in [
            self.settings.paths.output_videos,
            self.settings.paths.output_audio,
            self.settings.paths.output_subtitles,
            self.settings.paths.output_scripts,
            self.settings.paths.queue_jobs,
        ]:
            for artifact_path in directory.glob("*"):
                if artifact_path.is_file():
                    artifact_path.unlink()
