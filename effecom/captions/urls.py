from django.urls import path

from .views import (
    VideoCaptionDownloadView,
    VideoCaptionsView,
    VideoDetailView,
    VideoListCreateView,
    VideoMediaView,
    VideoProcessView,
)


urlpatterns = [
    path("videos/", VideoListCreateView.as_view(), name="caption-video-list"),
    path(
        "videos/<uuid:video_id>/",
        VideoDetailView.as_view(),
        name="caption-video-detail",
    ),
    path(
        "videos/<uuid:video_id>/process/",
        VideoProcessView.as_view(),
        name="caption-video-process",
    ),
    path(
        "videos/<uuid:video_id>/captions/",
        VideoCaptionsView.as_view(),
        name="caption-video-captions",
    ),
    path(
        "videos/<uuid:video_id>/captions/download/",
        VideoCaptionDownloadView.as_view(),
        name="caption-video-caption-download",
    ),
    path(
        "videos/<uuid:video_id>/media/",
        VideoMediaView.as_view(),
        name="caption-video-media",
    ),
]
