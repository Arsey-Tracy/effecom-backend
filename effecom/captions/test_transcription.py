import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, call, patch

from celery.exceptions import Retry
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from captions.models import CaptionTrack, Video
from captions.services.errors import (
    MediaProcessingError,
    RetryableTranscriptionError,
    TranscriptionModelError,
)
from captions.services.pipeline import _make_progress_callback
from captions.services.stale_jobs import fail_stale_caption_jobs
from captions.services.transcription_engine import (
    WhisperOptions,
    _load_model,
    transcribe_audio,
)
from captions.tasks import transcribe_video


def whisper_options(**overrides):
    values = {
        "model_size": "base",
        "device": "cpu",
        "compute_type": "int8",
        "language": "auto",
        "beam_size": 5,
        "vad_filter": True,
        "word_timestamps": False,
    }
    values.update(overrides)
    return WhisperOptions(**values)


class TranscriptionEngineTests(SimpleTestCase):
    def tearDown(self):
        _load_model.cache_clear()

    def test_model_load_is_lazy_cached_and_segments_are_filtered(self):
        words = [
            SimpleNamespace(start=0.1, end=0.3, word=" hello"),
            SimpleNamespace(start=float("nan"), end=0.4, word="bad"),
        ]
        model = Mock()
        model.transcribe.return_value = (
            iter(
                [
                    SimpleNamespace(
                        start=0.0,
                        end=0.5,
                        text=" hello ",
                        words=words,
                    ),
                    SimpleNamespace(
                        start=0.5,
                        end=float("inf"),
                        text="bad timestamp",
                        words=[],
                    ),
                ]
            ),
            SimpleNamespace(language="en"),
        )
        progress = []
        with patch("faster_whisper.WhisperModel", return_value=model) as model_class:
            options = whisper_options(word_timestamps=True)
            first = transcribe_audio(
                "unused.wav",
                duration_seconds=1.0,
                options=options,
                progress_callback=progress.append,
            )
            transcribe_audio(
                "unused.wav",
                duration_seconds=1.0,
                options=options,
            )

        model_class.assert_called_once_with("base", device="cpu", compute_type="int8")
        model.transcribe.assert_called_with(
            "unused.wav",
            language=None,
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )
        self.assertEqual(progress, [50])
        self.assertEqual(first.language, "en")
        self.assertEqual(
            first.segments,
            [
                {
                    "id": "1",
                    "start": 0.0,
                    "end": 0.5,
                    "text": "hello",
                    "words": [{"start": 0.1, "end": 0.3, "text": "hello"}],
                }
            ],
        )

    def test_explicit_language_and_empty_audio_are_supported(self):
        model = Mock()
        model.transcribe.return_value = (iter(()), SimpleNamespace(language=None))
        with patch("faster_whisper.WhisperModel", return_value=model):
            result = transcribe_audio(
                "unused.wav",
                duration_seconds=1.0,
                options=whisper_options(language="fr"),
            )

        self.assertEqual(result.language, None)
        self.assertEqual(result.segments, [])
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "fr")

    def test_model_load_failure_is_wrapped_without_exposing_provider_details(self):
        with patch(
            "faster_whisper.WhisperModel",
            side_effect=RuntimeError("private model-cache path"),
        ):
            with self.assertRaises(TranscriptionModelError) as raised:
                transcribe_audio(
                    "unused.wav",
                    duration_seconds=1.0,
                    options=whisper_options(),
                )

        self.assertNotIn("private model-cache path", str(raised.exception))


class CaptionProgressTests(SimpleTestCase):
    @override_settings(CAPTION_PROGRESS_WRITE_INTERVAL_SECONDS=3)
    def test_progress_updates_are_throttled(self):
        with patch("captions.services.pipeline._report_progress") as report_progress:
            with patch(
                "captions.services.pipeline.time.monotonic",
                side_effect=[0, 1, 2.9, 3, 6],
            ):
                report = _make_progress_callback("video-id")
                report(10)
                report(20)
                report(30)
                report(40)

        self.assertEqual(
            report_progress.call_args_list,
            [call("video-id", 30), call("video-id", 40)],
        )


def _create_video(path, *, include_audio):
    command = [
        shutil.which("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:r=10:d=0.4",
    ]
    if include_audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:sample_rate=16000:duration=0.4",
                "-shortest",
            ]
        )
    command.extend(
        [
            "-c:v",
            "mpeg4",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ]
    )
    subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        shell=False,
    )


@skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "FFmpeg and FFprobe are required for pipeline tests.",
)
class CaptionTaskTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_directory = tempfile.TemporaryDirectory(
            prefix="caption-task-tests-"
        )
        cls.video_with_audio = Path(cls.source_directory.name) / "with-audio.mp4"
        cls.video_without_audio = Path(cls.source_directory.name) / "without-audio.mp4"
        _create_video(cls.video_with_audio, include_audio=True)
        _create_video(cls.video_without_audio, include_audio=False)

    @classmethod
    def tearDownClass(cls):
        cls.source_directory.cleanup()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.media_directory = tempfile.TemporaryDirectory(
            prefix="caption-task-media-"
        )
        media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_settings.enable()
        self.addCleanup(self.media_directory.cleanup)
        self.addCleanup(media_settings.disable)

        self.user = get_user_model().objects.create_user(
            username="caption-worker@example.com",
            email="caption-worker@example.com",
            password="test-password",
        )
        self.video = self._make_video(self.video_with_audio)

        _load_model.cache_clear()
        self.addCleanup(_load_model.cache_clear)
        self.fake_model = Mock()
        self.set_transcript(
            [
                SimpleNamespace(
                    start=0.0,
                    end=0.25,
                    text=" Hello there. ",
                    words=[],
                )
            ]
        )
        model_patcher = patch(
            "faster_whisper.WhisperModel",
            return_value=self.fake_model,
        )
        model_patcher.start()
        self.addCleanup(model_patcher.stop)

    def _make_video(self, source_path, *, status=Video.Status.QUEUED):
        upload = SimpleUploadedFile(
            source_path.name,
            source_path.read_bytes(),
            content_type="application/octet-stream",
        )
        return Video.objects.create(
            user=self.user,
            title=source_path.stem,
            original_video=upload,
            duration=0.4,
            file_size=upload.size,
            status=status,
            heartbeat_at=timezone.now(),
        )

    def set_transcript(self, segments, *, language="en"):
        self.fake_model.transcribe.return_value = (
            iter(segments),
            SimpleNamespace(language=language),
        )

    def test_success_writes_track_and_marks_video_complete(self):
        self.assertEqual(transcribe_video.run(str(self.video.pk)), "completed")

        self.video.refresh_from_db()
        track = CaptionTrack.objects.get(video=self.video)
        self.assertEqual(self.video.status, Video.Status.COMPLETED)
        self.assertEqual(self.video.progress, 100)
        self.assertEqual(self.video.detected_language, "en")
        self.assertEqual(track.segments[0]["text"], "Hello there.")
        self.assertTrue(self.video.original_video.storage.exists(
            self.video.original_video.name
        ))

    def test_silent_audio_completes_with_an_empty_track(self):
        self.set_transcript([], language=None)

        transcribe_video.run(str(self.video.pk))

        self.video.refresh_from_db()
        track = CaptionTrack.objects.get(video=self.video)
        self.assertEqual(self.video.status, Video.Status.COMPLETED)
        self.assertEqual(track.language, "und")
        self.assertEqual(track.segments, [])

    def test_video_without_audio_fails_with_a_safe_message(self):
        video = self._make_video(self.video_without_audio)

        with self.assertRaises(MediaProcessingError):
            transcribe_video.run(str(video.pk))

        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.FAILED)
        self.assertIn("audio stream", video.error_message)
        self.assertFalse(CaptionTrack.objects.filter(video=video).exists())

    def test_ffmpeg_failure_fails_without_deleting_the_original_video(self):
        with patch(
            "captions.services.pipeline.extract_audio",
            side_effect=MediaProcessingError("Audio extraction failed safely."),
        ):
            with self.assertRaises(MediaProcessingError):
                transcribe_video.run(str(self.video.pk))

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.FAILED)
        self.assertTrue(
            self.video.original_video.storage.exists(self.video.original_video.name)
        )
        self.assertEqual(self.video.error_message, "Audio extraction failed safely.")

    def test_model_load_failure_marks_video_failed_after_retry_limit(self):
        model_patcher = patch(
            "faster_whisper.WhisperModel",
            side_effect=RuntimeError("private model-cache path"),
        )
        model_patcher.start()
        self.addCleanup(model_patcher.stop)
        _load_model.cache_clear()

        transcribe_video.push_request(retries=settings.CAPTION_TASK_MAX_RETRIES)
        try:
            with self.assertRaises(TranscriptionModelError):
                transcribe_video.run(str(self.video.pk))
        finally:
            transcribe_video.pop_request()

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.FAILED)
        self.assertNotIn("private model-cache path", self.video.error_message)

    def test_duplicate_delivery_does_not_create_another_track(self):
        self.assertEqual(transcribe_video.run(str(self.video.pk)), "completed")
        self.assertEqual(transcribe_video.run(str(self.video.pk)), "skipped")

        self.assertEqual(CaptionTrack.objects.filter(video=self.video).count(), 1)
        self.fake_model.transcribe.assert_called_once()

    def test_transient_failure_requeues_and_can_be_retried(self):
        with patch(
            "captions.tasks.process_video",
            side_effect=RetryableTranscriptionError("temporary model error"),
        ):
            with patch.object(
                transcribe_video,
                "retry",
                side_effect=Retry("retry"),
            ):
                with self.assertRaises(Retry):
                    transcribe_video.run(str(self.video.pk))

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.QUEUED)
        self.assertEqual(transcribe_video.run(str(self.video.pk)), "completed")
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.Status.COMPLETED)


class StaleCaptionJobTests(TestCase):
    def test_management_command_fails_only_jobs_with_expired_heartbeats(self):
        user = get_user_model().objects.create_user(
            username="stale-caption@example.com",
            email="stale-caption@example.com",
            password="test-password",
        )
        now = timezone.now()
        stale = Video.objects.create(
            user=user,
            title="Stale job",
            original_video="captions/videos/stale.mp4",
            status=Video.Status.TRANSCRIBING,
            started_at=now - timedelta(minutes=20),
            heartbeat_at=now - timedelta(minutes=20),
        )
        fresh = Video.objects.create(
            user=user,
            title="Fresh job",
            original_video="captions/videos/fresh.mp4",
            status=Video.Status.TRANSCRIBING,
            started_at=now,
            heartbeat_at=now,
        )
        with override_settings(CAPTION_STALE_JOB_MINUTES=15):
            call_command("recover_stale_caption_jobs")

        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stale.status, Video.Status.FAILED)
        self.assertIn("Retry", stale.error_message)
        self.assertEqual(fresh.status, Video.Status.TRANSCRIBING)

    def test_stale_recovery_service_returns_updated_count(self):
        user = get_user_model().objects.create_user(
            username="stale-count@example.com",
            email="stale-count@example.com",
            password="test-password",
        )
        Video.objects.create(
            user=user,
            title="Stale queued",
            original_video="captions/videos/stale-queued.mp4",
            status=Video.Status.QUEUED,
            heartbeat_at=timezone.now() - timedelta(minutes=30),
        )

        with override_settings(CAPTION_STALE_JOB_MINUTES=15):
            self.assertEqual(fail_stale_caption_jobs(), 1)
