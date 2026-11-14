class MediaProcessingError(Exception):
    pass


class TranscriptionError(Exception):
    pass


class RetryableTranscriptionError(Exception):
    pass


class TranscriptionModelError(RetryableTranscriptionError):
    pass


class CaptionStorageError(Exception):
    pass


class VideoStateConflict(Exception):
    pass


class CaptionVersionConflict(Exception):
    def __init__(self, current_version):
        self.current_version = current_version
        super().__init__("The caption track version is out of date.")


class TaskQueueUnavailable(Exception):
    pass


class CaptionProcessingUnavailable(Exception):
    pass
