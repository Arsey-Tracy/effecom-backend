from django.urls import reverse
from rest_framework import serializers

from .models import CaptionTrack, Video


class VideoUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=False)


class VideoSerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = (
            "id",
            "title",
            "duration",
            "file_size",
            "detected_language",
            "status",
            "progress",
            "stage",
            "error_message",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
            "media_url",
        )
        read_only_fields = fields

    def get_media_url(self, video):
        return reverse("caption-video-media", kwargs={"video_id": video.pk})


class CaptionTrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaptionTrack
        fields = ("language", "segments", "version", "created_at", "updated_at")
        read_only_fields = fields


class CaptionUpdateSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    segments = serializers.ListField(child=serializers.DictField())
    deleted_ids = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        default=list,
    )


class CaptionQuerySerializer(serializers.Serializer):
    language = serializers.CharField(max_length=32, required=False, allow_blank=False)


class CaptionDownloadQuerySerializer(CaptionQuerySerializer):
    format = serializers.ChoiceField(
        choices=("srt", "vtt"),
        default="srt",
        required=False,
    )
