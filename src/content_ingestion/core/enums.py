from enum import Enum


class FetchStatus(str, Enum):
    OK = "ok"
    AUTH_REQUIRED = "auth_required"
    NOT_SUPPORTED = "not_supported"
    FAILED = "failed"
