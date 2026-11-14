import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework.test import APIClient, APITestCase

from captions.models import CaptionTrack, CaptionUploadTicket, Video


def _create_sample_video(path):
    subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=10:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=16000:duration=0.4",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        shell=False,
    )


class CaptionApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="video-owner@example.com",
            email="video-owner@example.com",
            password="test-password",
        )
        cls.other_user = user_model.objects.create_user(
            username="other-video-owner@example.com",
            email="other-video-owner@example.com",
            password="test-password",
        )

    def setUp(self):
        super().setUp()
        self.media_directory = tempfile.TemporaryDirectory(
            prefix="caption-api-media-"
        )
        media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.addCleanup(self.media_directory.cleanup)
        self.client.force_authenticate(self.user)

        self.video = self._make_video(self.user)
        self.other_video = self._make_video(self.other_user)
        self.track = CaptionTrack.objects.create(
            video=self.video,
            language="en",
            segments=[
                {
                    "id": "first",
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Hello.",
                    "words": [{"start": 0.1, "end": 0.5, "text": "Hello."}],
                },
                {
                    "id": "second",
                    "start": 1.0,
                    "end": 2.0,
                    "text": "World.",
                },
            ],
        )

    def _make_video(self, user, *, status=Video.Status.COMPLETED):
        content = b"0123456789"
        upload = SimpleUploadedFile(
            "private.mp4",
            content,
            content_type="video/mp4",
        )
        return Video.objects.create(
            user=user,
            title="Private clip",
            original_video=upload,
            duration=5.0,
            file_size=len(content),
            detected_language="en",
            status=status,
            progress=100 if status == Video.Status.COMPLETED else 0,
            stage="Completed" if status == Video.Status.COMPLETED else "",
            heartbeat_at=timezone.now(),
        )

    def test_video_list_is_paginated_and_contains_only_the_authenticated_users(self):
        self._make_video(self.user)

        response = self.client.get("/api/v1/videos/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertNotIn(
            str(self.other_video.pk),
            [video["id"] for video in response.data["results"]],
        )
        self.assertNotIn("original_video", response.data["results"][0])
        self.assertNotIn("private.mp4", str(response.data))

    def test_video_endpoints_require_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get("/api/v1/videos/")

        self.assertEqual(response.status_code, 401)

    def test_upload_ticket_is_user_bound_and_consumed_once(self):
        anonymous_client = APIClient()
        unauthorized = anonymous_client.post(
            "/api/v1/videos/upload-ticket/",
            {},
            format="json",
        )
        self.assertEqual(unauthorized.status_code, 401)

        ticket_response = self.client.post(
            "/api/v1/videos/upload-ticket/",
            {},
            format="json",
        )
        self.assertEqual(ticket_response.status_code, 201)
        token = ticket_response.data["ticket"]
        ticket = CaptionUploadTicket.objects.get(user=self.user)
        self.assertNotEqual(ticket.token_hash, token)
        self.assertGreater(ticket.expires_at, timezone.now())

        upload_client = APIClient()
        with patch("captions.views.create_video", return_value=self.video) as create:
            response = upload_client.post(
                "/api/v1/videos/upload/",
                {"file": SimpleUploadedFile("clip.mp4", b"video")},
                format="multipart",
                HTTP_AUTHORIZATION=f"CaptionUpload {token}",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(create.call_args.kwargs["user"], self.user)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.used_at)

        with patch("captions.views.create_video") as create:
            reused = upload_client.post(
                "/api/v1/videos/upload/",
                {"file": SimpleUploadedFile("clip.mp4", b"video")},
                format="multipart",
                HTTP_AUTHORIZATION=f"CaptionUpload {token}",
            )
        self.assertEqual(reused.status_code, 401)
        create.assert_not_called()

    def test_direct_upload_cors_preflight_allows_ticket_authorization(self):
        response = APIClient().options(
            "/api/v1/videos/upload/",
            HTTP_ORIGIN="https://effecom.vercel.app",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Access-Control-Allow-Origin"],
            "https://effecom.vercel.app",
        )
        self.assertIn("authorization", response["Access-Control-Allow-Headers"].lower())

    def test_upload_ticket_is_scoped_to_the_direct_upload_endpoint_and_expires(self):
        ticket_response = self.client.post(
            "/api/v1/videos/upload-ticket/",
            {},
            format="json",
        )
        token = ticket_response.data["ticket"]
        upload_client = APIClient()

        list_response = upload_client.get(
            "/api/v1/videos/",
            HTTP_AUTHORIZATION=f"CaptionUpload {token}",
        )
        self.assertEqual(list_response.status_code, 401)
        ticket = CaptionUploadTicket.objects.get(user=self.user)
        self.assertIsNone(ticket.used_at)

        ticket.expires_at = timezone.now() - timedelta(seconds=1)
        ticket.save(update_fields=("expires_at",))
        expired = upload_client.post(
            "/api/v1/videos/upload/",
            {"file": SimpleUploadedFile("clip.mp4", b"video")},
            format="multipart",
            HTTP_AUTHORIZATION=f"CaptionUpload {token}",
        )
        self.assertEqual(expired.status_code, 401)

    def test_another_user_cannot_read_or_delete_a_video(self):
        response = self.client.get(f"/api/v1/videos/{self.other_video.pk}/")
        self.assertEqual(response.status_code, 404)

        response = self.client.delete(f"/api/v1/videos/{self.other_video.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Video.objects.filter(pk=self.other_video.pk).exists())

    def test_upload_rejects_disallowed_extensions_and_oversized_files(self):
        invalid_extension = SimpleUploadedFile("clip.txt", b"not a video")
        response = self.client.post(
            "/api/v1/videos/",
            {"file": invalid_extension},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

        oversized = SimpleUploadedFile("large.mp4", b"x" * (1024 * 1024 + 1))
        with override_settings(CAPTION_MAX_UPLOAD_MB=1):
            response = self.client.post(
                "/api/v1/videos/",
                {"file": oversized},
                format="multipart",
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Video.objects.filter(user=self.user).count(), 1)

    @skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "FFmpeg and FFprobe are required for upload API tests.",
    )
    def test_validated_upload_stores_video_without_exposing_its_storage_path(self):
        with tempfile.TemporaryDirectory(prefix="caption-api-upload-") as directory:
            path = Path(directory) / "sample.mp4"
            _create_sample_video(path)
            upload = SimpleUploadedFile(
                "sample.mp4",
                path.read_bytes(),
                content_type="application/octet-stream",
            )
            response = self.client.post(
                "/api/v1/videos/",
                {"file": upload, "title": "Uploaded clip"},
                format="multipart",
            )

        self.assertEqual(response.status_code, 201)
        video = Video.objects.get(pk=response.data["id"])
        self.assertEqual(video.title, "Uploaded clip")
        self.assertGreater(video.duration, 0)
        self.assertEqual(video.file_size, response.data["file_size"])
        self.assertIn("/api/v1/videos/", response.data["media_url"])
        self.assertNotIn(video.original_video.name, str(response.data))

    def test_delete_removes_the_private_file_and_video_record(self):
        stored_name = self.video.original_video.name
        storage = self.video.original_video.storage
        self.assertTrue(storage.exists(stored_name))

        response = self.client.delete(f"/api/v1/videos/{self.video.pk}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(storage.exists(stored_name))
        self.assertFalse(Video.objects.filter(pk=self.video.pk).exists())
        self.assertFalse(CaptionTrack.objects.filter(pk=self.track.pk).exists())

    def test_processing_queues_uploaded_videos_and_failed_videos_can_retry(self):
        uploaded = self._make_video(self.user, status=Video.Status.UPLOADED)
        failed = self._make_video(self.user, status=Video.Status.FAILED)
        failed.error_message = "Previous attempt failed."
        failed.save(update_fields=("error_message",))

        with patch("captions.services.videos.transcribe_video.delay") as enqueue:
            response = self.client.post(
                f"/api/v1/videos/{uploaded.pk}/process/",
                {},
                format="json",
            )
            self.assertEqual(response.status_code, 202)
            enqueue.assert_called_once_with(str(uploaded.pk))

        uploaded.refresh_from_db()
        self.assertEqual(uploaded.status, Video.Status.QUEUED)
        self.assertEqual(uploaded.error_message, "")

        with patch("captions.services.videos.transcribe_video.delay"):
            response = self.client.post(
                f"/api/v1/videos/{failed.pk}/process/",
                {},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        failed.refresh_from_db()
        self.assertEqual(failed.status, Video.Status.QUEUED)
        self.assertEqual(failed.error_message, "")

    def test_processing_rejects_disallowed_states_and_handles_broker_failure(self):
        with patch("captions.services.videos.transcribe_video.delay") as enqueue:
            response = self.client.post(
                f"/api/v1/videos/{self.video.pk}/process/",
                {},
                format="json",
            )
        self.assertEqual(response.status_code, 409)
        enqueue.assert_not_called()

        queued = self._make_video(self.user, status=Video.Status.UPLOADED)
        with patch(
            "captions.services.videos.transcribe_video.delay",
            side_effect=OperationalError("private broker address"),
        ):
            response = self.client.post(
                f"/api/v1/videos/{queued.pk}/process/",
                {},
                format="json",
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private broker address", str(response.data))
        queued.refresh_from_db()
        self.assertEqual(queued.status, Video.Status.FAILED)

    def test_caption_patch_preserves_untouched_segments_and_checks_version(self):
        response = self.client.get(
            f"/api/v1/videos/{self.video.pk}/captions/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 1)

        response = self.client.patch(
            f"/api/v1/videos/{self.video.pk}/captions/",
            {
                "version": 1,
                "segments": [{"id": "first", "text": "Updated hello."}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(response.data["segments"][0]["text"], "Updated hello.")
        self.assertEqual(
            response.data["segments"][0]["words"],
            [{"start": 0.1, "end": 0.5, "text": "Hello."}],
        )
        self.assertEqual(response.data["segments"][1]["id"], "second")

        response = self.client.patch(
            f"/api/v1/videos/{self.video.pk}/captions/",
            {"version": 1, "segments": [{"id": "first", "text": "Stale edit"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["details"]["current_version"], 2)

    def test_caption_patch_validates_all_segments_and_supports_explicit_deletion(self):
        response = self.client.patch(
            f"/api/v1/videos/{self.video.pk}/captions/",
            {
                "version": 1,
                "segments": [
                    {"id": "first", "start": 5.0, "end": 6.0, "text": "Too late"}
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.track.refresh_from_db()
        self.assertEqual(self.track.version, 1)
        self.assertEqual(len(self.track.segments), 2)

        response = self.client.patch(
            f"/api/v1/videos/{self.video.pk}/captions/",
            {"version": 1, "segments": [], "deleted_ids": ["first"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [segment["id"] for segment in response.data["segments"]],
            ["second"],
        )

    def test_another_user_cannot_read_or_edit_captions(self):
        self.client.force_authenticate(self.other_user)

        response = self.client.get(
            f"/api/v1/videos/{self.video.pk}/captions/"
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.patch(
            f"/api/v1/videos/{self.video.pk}/captions/",
            {"version": 1, "segments": []},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_download_exports_saved_captions_with_format_headers(self):
        srt = self.client.get(
            f"/api/v1/videos/{self.video.pk}/captions/download/?format=srt"
        )
        self.assertEqual(srt.status_code, 200)
        self.assertTrue(srt["Content-Type"].startswith("application/x-subrip"))
        self.assertIn('attachment; filename="captions-', srt["Content-Disposition"])
        self.assertIn("Hello.", srt.content.decode("utf-8"))

        vtt = self.client.get(
            f"/api/v1/videos/{self.video.pk}/captions/download/?format=vtt"
        )
        self.assertEqual(vtt.status_code, 200)
        self.assertTrue(vtt["Content-Type"].startswith("text/vtt"))
        self.assertTrue(vtt.content.startswith(b"WEBVTT"))

        invalid = self.client.get(
            f"/api/v1/videos/{self.video.pk}/captions/download/?format=txt"
        )
        self.assertEqual(invalid.status_code, 400)

    def test_media_endpoint_authenticates_supports_ranges_and_hides_other_users_files(self):
        response = self.client.get(
            f"/api/v1/videos/{self.video.pk}/media/",
            HTTP_RANGE="bytes=2-5",
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(b"".join(response.streaming_content), b"2345")
        self.assertEqual(response["Content-Range"], "bytes 2-5/10")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        response.close()

        invalid_range = self.client.get(
            f"/api/v1/videos/{self.video.pk}/media/",
            HTTP_RANGE="bytes=99-100",
        )
        self.assertEqual(invalid_range.status_code, 416)
        self.assertEqual(invalid_range["Content-Range"], "bytes */10")

        response = self.client.get(
            f"/api/v1/videos/{self.other_video.pk}/media/"
        )
        self.assertEqual(response.status_code, 404)

        self.client.force_authenticate(user=None)
        response = self.client.get(f"/api/v1/videos/{self.video.pk}/media/")
        self.assertEqual(response.status_code, 401)
