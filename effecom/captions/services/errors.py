class MediaProcessingError(Exception):
    pass


class TranscriptionError(Exception):
    pass


class RetryableTranscriptionError(Exception):
    pass


class TranscriptionModelError(RetryableTranscriptionError):
    pass
