from app.core.errors import DomainError


class FileTooLarge(DomainError):
    status = 413
    code = "FILE_TOO_LARGE"
    default_message = "Файл больше допустимого размера"


class UnsupportedMediaType(DomainError):
    status = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    default_message = "Поддерживаются только JPEG, PNG и WebP"
