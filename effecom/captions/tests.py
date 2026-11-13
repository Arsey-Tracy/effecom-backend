import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from .models import video_upload_path
from .services.audio_extractor import extract_audio
from .services.errors import MediaProcessingError
from .services.subtitle_exporter import export_track, render_srt, render_vtt
from .services.video_probe import VideoProbe, probe_video, validate_video_upload
from .validators import validate_caption_segments


class CaptionSegmentValidatorTests(SimpleTestCase):
    def test_video_storage_path_uses_only_a_random_name_and_allowed_extension(self):
        stored_path = video_upload_path(None, "../../private/clip.mp4")
        self.assertRegex(
            stored_path,
            r"^captions/videos/[0-9a-f]{32}\.mp4$",
        )
        self.assertRegex(
            video_upload_path(None, "../../private/secret.exe"),
            r"^captions/videos/[0-9a-f]{32}$",
        )

    def setUp(self):
        self.segments = [
            {"id": "first", "start": 0.0, "end": 1.25, "text": "Hello."},
            {
                "id": "second",
                "start": 1.25,
                "end": 2.5,
                "text": "World.",
                "words": [
                    {"start": 1.25, "end": 1.75, "text": "World."},
                ],
            },
        ]

    def test_accepts_ordered_segments_and_optional_words(self):
        self.assertIsNone(validate_caption_segments(self.segments, 3.0))

    def test_rejects_non_finite_or_invalid_time_ranges(self):
        invalid_values = (
            (float("nan"), 1.0),
            (0.0, float("inf")),
            (10**400, 10**400 + 1),
            (-0.1, 1.0),
            (1.0, 1.0),
            (0.0, 3.1),
            (True, 1.0),
        )
        for start, end in invalid_values:
            with self.subTest(start=start, end=end):
                segment = {"id": "one", "start": start, "end": end, "text": "Hi"}
                with self.assertRaises(ValidationError):
                    validate_caption_segments([segment], 3.0)

    def test_rejects_empty_text_duplicate_ids_and_out_of_order_segments(self):
        empty_text = [{"id": "one", "start": 0, "end": 1, "text": "  "}]
        duplicate_ids = [
            {"id": "same", "start": 0, "end": 1, "text": "One"},
            {"id": "same", "start": 1, "end": 2, "text": "Two"},
        ]
        out_of_order = [
            {"id": "later", "start": 1, "end": 2, "text": "Later"},
            {"id": "earlier", "start": 0, "end": 1, "text": "Earlier"},
        ]

        for segments in (empty_text, duplicate_ids, out_of_order):
            with self.subTest(segments=segments):
                with self.assertRaises(ValidationError):
                    validate_caption_segments(segments, 3.0)

    def test_rejects_invalid_word_timings(self):
        segment = {
            "id": "one",
            "start": 0.0,
            "end": 2.0,
            "text": "Hello there.",
            "words": [
                {"start": 0.9, "end": 1.1, "text": "there"},
                {"start": 0.2, "end": 0.4, "text": "Hello"},
            ],
        }
        with self.assertRaises(ValidationError):
            validate_caption_segments([segment], 3.0)


class SubtitleExporterTests(SimpleTestCase):
    def setUp(self):
        self.segments = [
            {
                "id": "one",
                "start": 0.5,
                "end": 2.345,
                "text": "Caf\u00e9\r\nwith a line break",
            },
            {"id": "two", "start": 2.345, "end": 3.0, "text": "Fin."},
        ]

    def test_srt_uses_comma_milliseconds_utf8_text_and_normalized_newlines(self):
        self.assertEqual(
            render_srt(self.segments),
            "1\n00:00:00,500 --> 00:00:02,345\nCaf\u00e9\nwith a line break\n\n"
            "2\n00:00:02,345 --> 00:00:03,000\nFin.\n",
        )

    def test_vtt_has_header_and_period_milliseconds(self):
        self.assertEqual(
            render_vtt([self.segments[0]]),
            "WEBVTT\n\n1\n00:00:00.500 --> 00:00:02.345\n"
            "Caf\u00e9\nwith a line break\n",
        )
        self.assertEqual(render_vtt([]), "WEBVTT\n")

    def test_exporter_preserves_positive_intervals_at_millisecond_precision(self):
        segments = [{"id": "tiny", "start": 0.0001, "end": 0.0002, "text": "Hi"}]
        self.assertIn("00:00:00,000 --> 00:00:00,001", render_srt(segments))
        self.assertIn("00:00:00.000 --> 00:00:00.001", render_vtt(segments))

    def test_export_track_reads_the_track_segments(self):
        track = SimpleNamespace(segments=self.segments)
        self.assertEqual(export_track(track, "srt"), render_srt(self.segments))
        self.assertEqual(export_track(track, "vtt"), render_vtt(self.segments))
        with self.assertRaises(ValueError):
            export_track(track, "txt")


@skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "FFmpeg and FFprobe are required for media service tests.",
)
class MediaServiceTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.temp_directory = tempfile.TemporaryDirectory(prefix="caption-tests-")
        cls.video_path = Path(cls.temp_directory.name) / "sample.mp4"
        cls.video_without_audio_path = (
            Path(cls.temp_directory.name) / "video-without-audio.mp4"
        )
        cls._create_video(cls.video_path, include_audio=True)
        cls._create_video(cls.video_without_audio_path, include_audio=False)

    @classmethod
    def tearDownClass(cls):
        cls.temp_directory.cleanup()
        super().tearDownClass()

    @classmethod
    def _create_video(cls, path, *, include_audio):
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

    def uploaded_video(self, *, name="sample.mp4", content_type="application/octet-stream"):
        return SimpleUploadedFile(
            name,
            self.video_path.read_bytes(),
            content_type=content_type,
        )

    def test_probe_returns_duration_and_requires_video_and_audio(self):
        probe = probe_video(self.video_path)
        self.assertGreater(probe.duration_seconds, 0)
        self.assertTrue(probe.has_video)
        self.assertTrue(probe.has_audio)
        with self.assertRaises(MediaProcessingError):
            probe_video(self.video_without_audio_path)

    def test_upload_validation_checks_content_not_declared_mime_type(self):
        probe = validate_video_upload(self.uploaded_video())
        self.assertTrue(probe.has_video)
        self.assertTrue(probe.has_audio)

    def test_upload_validation_rejects_bad_extension_before_probing(self):
        upload = self.uploaded_video(name="sample.txt")
        with patch("captions.services.video_probe.probe_video") as mock_probe:
            with self.assertRaises(ValidationError):
                validate_video_upload(upload)
        mock_probe.assert_not_called()

    @override_settings(CAPTION_MAX_UPLOAD_MB=1)
    def test_upload_validation_enforces_size_limit_before_probing(self):
        upload = SimpleUploadedFile("large.mp4", b"x" * (1024 * 1024 + 1))
        with patch("captions.services.video_probe.probe_video") as mock_probe:
            with self.assertRaises(ValidationError):
                validate_video_upload(upload)
        mock_probe.assert_not_called()

    @override_settings(CAPTION_MAX_DURATION_MIN=1)
    def test_upload_validation_enforces_duration_limit(self):
        upload = self.uploaded_video()
        with patch(
            "captions.services.video_probe.probe_video",
            return_value=VideoProbe(61 * 60, True, True),
        ):
            with self.assertRaises(ValidationError):
                validate_video_upload(upload)

    def test_audio_extraction_produces_mono_16khz_wav_and_cleans_up(self):
        with extract_audio(self.video_path) as audio_path:
            self.assertTrue(audio_path.is_file())
            audio_path = Path(audio_path)
            probe_command = [
                shutil.which("ffprobe"),
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,channels,sample_rate",
                "-of",
                "json",
                str(audio_path),
            ]
            result = subprocess.run(
                probe_command,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
                shell=False,
            )
            stream = json.loads(result.stdout)["streams"][0]
            self.assertEqual(stream["channels"], 1)
            self.assertEqual(stream["sample_rate"], "16000")
            temporary_audio_path = audio_path

        self.assertFalse(temporary_audio_path.exists())

    def test_audio_extraction_reports_ffmpeg_failure(self):
        with patch(
            "captions.services.audio_extractor.subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", "error"),
        ):
            with self.assertRaises(MediaProcessingError):
                with extract_audio(self.video_path):
                    self.fail("Audio extraction should not yield after a failure.")
