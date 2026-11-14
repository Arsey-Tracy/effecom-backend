import mimetypes
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import exceptions
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from translation.api import V1APIView

from .authentication import CaptionUploadTicketAuthentication
from .models import CaptionTrack
from .serializers import (
    CaptionDownloadQuerySerializer,
    CaptionQuerySerializer,
    CaptionTrackSerializer,
    CaptionUpdateSerializer,
    VideoSerializer,
    VideoUploadSerializer,
)
from .services.errors import (
    CaptionStorageError,
    CaptionVersionConflict,
    TaskQueueUnavailable,
    VideoStateConflict,
)
from .services.subtitle_exporter import export_track
from .services.videos import (
    create_video,
    delete_video,
    get_caption_track,
    get_owned_video,
    owned_videos,
    queue_video,
    update_caption_track,
)
from .services.upload_tickets import issue_upload_ticket


class CaptionAPIView(V1APIView):
    permission_classes = [IsAuthenticated]


class CaptionDownloadContentNegotiation(DefaultContentNegotiation):
    def select_renderer(self, request, renderers, format_suffix=None):
        renderer_suffix = format_suffix if format_suffix == "json" else "json"
        return super().select_renderer(
            request,
            renderers,
            format_suffix=renderer_suffix,
        )


class VideoPagination(PageNumberPagination):
    page_size = 20


class VideoConflict(exceptions.APIException):
    status_code = 409
    default_code = "invalid_video_state"
    default_detail = "The video is not in a state that can be processed."


class CaptionQueueUnavailableResponse(exceptions.APIException):
    status_code = 503
    default_code = "caption_queue_unavailable"
    default_detail = "The transcription job could not be queued. Please retry."


class CaptionStorageUnavailableResponse(exceptions.APIException):
    status_code = 503
    default_code = "caption_storage_unavailable"
    default_detail = "Video storage is temporarily unavailable."


def _owned_video_or_404(user, video_id):
    video = get_owned_video(user, video_id)
    if video is None:
        raise exceptions.NotFound("Video not found.")
    return video


def _caption_track_or_404(video, language):
    track = get_caption_track(video, language)
    if track is None:
        raise exceptions.NotFound("Caption track not found.")
    return track


def _byte_range(range_header, size):
    if range_header is None:
        return 0, max(size - 1, -1)
    if size <= 0:
        return None

    unit, separator, requested_range = range_header.partition("=")
    if (
        not separator
        or unit.strip().lower() != "bytes"
        or "," in requested_range
    ):
        return None

    start_text, separator, end_text = requested_range.partition("-")
    if not separator:
        return None
    try:
        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(size - suffix_length, 0)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
            if start < 0 or start >= size or end < start:
                return None
            end = min(end, size - 1)
    except (ValueError, OverflowError):
        return None
    return start, end


class _FileChunkIterator:
    def __init__(self, file_object, length):
        self.file_object = file_object
        self.remaining = length

    def __iter__(self):
        try:
            while self.remaining:
                chunk = self.file_object.read(min(64 * 1024, self.remaining))
                if not chunk:
                    break
                self.remaining -= len(chunk)
                yield chunk
        finally:
            self.close()

    def close(self):
        self.file_object.close()


def _stream_file(file_object, length):
    return _FileChunkIterator(file_object, length)


def _create_video_response(request):
    serializer = VideoUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        video = create_video(
            user=request.user,
            uploaded_file=serializer.validated_data["file"],
            title=serializer.validated_data.get("title"),
        )
    except DjangoValidationError as exc:
        raise exceptions.ValidationError({"file": exc.messages}) from exc
    except CaptionStorageError as exc:
        raise CaptionStorageUnavailableResponse() from exc
    return Response(VideoSerializer(video).data, status=201)


class VideoListCreateView(CaptionAPIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        paginator = VideoPagination()
        page = paginator.paginate_queryset(
            owned_videos(request.user),
            request,
            view=self,
        )
        return paginator.get_paginated_response(
            VideoSerializer(page, many=True).data
        )

    def post(self, request):
        return _create_video_response(request)


class VideoUploadTicketView(CaptionAPIView):
    def post(self, request):
        token, expires_at = issue_upload_ticket(request.user)
        return Response(
            {"ticket": token, "expires_at": expires_at},
            status=201,
        )


class DirectVideoUploadView(CaptionAPIView):
    authentication_classes = [CaptionUploadTicketAuthentication]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        return _create_video_response(request)


class VideoDetailView(CaptionAPIView):
    def get(self, request, video_id):
        video = _owned_video_or_404(request.user, video_id)
        return Response(VideoSerializer(video).data)

    def delete(self, request, video_id):
        video = _owned_video_or_404(request.user, video_id)
        try:
            delete_video(video)
        except CaptionStorageError as exc:
            raise CaptionStorageUnavailableResponse() from exc
        return Response(status=204)


class VideoProcessView(CaptionAPIView):
    def post(self, request, video_id):
        video = _owned_video_or_404(request.user, video_id)
        try:
            video = queue_video(video)
        except VideoStateConflict as exc:
            raise VideoConflict() from exc
        except TaskQueueUnavailable as exc:
            raise CaptionQueueUnavailableResponse() from exc
        if video is None:
            raise exceptions.NotFound("Video not found.")
        return Response(VideoSerializer(video).data, status=202)


class VideoCaptionsView(CaptionAPIView):
    def get(self, request, video_id):
        video = _owned_video_or_404(request.user, video_id)
        query = CaptionQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        track = _caption_track_or_404(
            video,
            query.validated_data.get("language"),
        )
        return Response(CaptionTrackSerializer(track).data)

    def patch(self, request, video_id):
        video = _owned_video_or_404(request.user, video_id)
        query = CaptionQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        track = _caption_track_or_404(
            video,
            query.validated_data.get("language"),
        )
        serializer = CaptionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            track = update_caption_track(
                video=video,
                language=track.language,
                version=serializer.validated_data["version"],
                segments=serializer.validated_data["segments"],
                deleted_ids=serializer.validated_data["deleted_ids"],
            )
        except CaptionTrack.DoesNotExist as exc:
            raise exceptions.NotFound("Caption track not found.") from exc
        except DjangoValidationError as exc:
            raise exceptions.ValidationError({"segments": exc.messages}) from exc
        except CaptionVersionConflict as exc:
            return Response(
                {
                    "error": {
                        "code": "caption_version_conflict",
                        "message": "Captions changed since they were loaded.",
                        "details": {"current_version": exc.current_version},
                    }
                },
                status=409,
            )
        return Response(CaptionTrackSerializer(track).data)


class VideoCaptionDownloadView(CaptionAPIView):
    content_negotiation_class = CaptionDownloadContentNegotiation

    def get(self, request, video_id):
        video = _owned_video_or_404(request.user, video_id)
        query = CaptionDownloadQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        track = _caption_track_or_404(
            video,
            query.validated_data.get("language"),
        )
        file_format = query.validated_data["format"]
        try:
            content = export_track(track, file_format)
        except DjangoValidationError as exc:
            raise exceptions.ValidationError({"segments": exc.messages}) from exc

        content_type = (
            "application/x-subrip; charset=utf-8"
            if file_format == "srt"
            else "text/vtt; charset=utf-8"
        )
        filename = f"captions-{video.pk}.{file_format}"
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "private, no-store"
        return response


class VideoMediaView(CaptionAPIView):
    def get(self, request, video_id):
        video = _owned_video_or_404(request.user, video_id)
        storage = video.original_video.storage
        stored_name = video.original_video.name
        try:
            size = storage.size(stored_name)
        except FileNotFoundError as exc:
            raise exceptions.NotFound("Video file not found.") from exc
        except OSError as exc:
            raise CaptionStorageUnavailableResponse() from exc

        requested_range = request.headers.get("Range")
        selected_range = _byte_range(requested_range, size)
        if selected_range is None:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            response["Accept-Ranges"] = "bytes"
            response["Content-Length"] = "0"
            return response
        start, end = selected_range
        length = max(end - start + 1, 0)

        file_object = None
        try:
            file_object = video.original_video.open("rb")
            file_object.seek(start)
        except FileNotFoundError as exc:
            if file_object is not None:
                file_object.close()
            raise exceptions.NotFound("Video file not found.") from exc
        except OSError as exc:
            if file_object is not None:
                file_object.close()
            raise CaptionStorageUnavailableResponse() from exc

        content_type = (
            mimetypes.guess_type(
                f"video{PurePosixPath(stored_name).suffix.lower()}"
            )[0]
            or "application/octet-stream"
        )
        response = StreamingHttpResponse(
            _stream_file(file_object, length),
            status=206 if requested_range is not None else 200,
            content_type=content_type,
        )
        if requested_range is not None:
            response["Content-Range"] = f"bytes {start}-{end}/{size}"

        response["Accept-Ranges"] = "bytes"
        response["Content-Length"] = str(length)
        response["Content-Disposition"] = (
            f'inline; filename="{video.pk}{PurePosixPath(stored_name).suffix.lower()}"'
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
