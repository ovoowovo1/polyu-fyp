# -*- coding: utf-8 -*-
from typing import Any


class ServiceError(RuntimeError):
    status_code = 500
    default_detail = "Internal server error"

    def __init__(self, detail: Any | None = None):
        self.detail = self.default_detail if detail is None else detail
        super().__init__(str(self.detail))


class NotFoundError(ServiceError):
    status_code = 404
    default_detail = "Not found"


class PermissionDeniedError(ServiceError):
    status_code = 403
    default_detail = "Permission denied"


class ValidationServiceError(ServiceError):
    status_code = 400
    default_detail = "Bad request"


class AlreadySubmittedError(ServiceError):
    status_code = 400
    default_detail = "The submission has already been submitted."


class NotReleasedError(ServiceError):
    status_code = 403
    default_detail = "The exam has not yet been released."
