import asyncio
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from app.routers import service_helpers
from app.services.core.exceptions import NotFoundError, ValidationServiceError


def capture_http_exception(awaitable):
    try:
        asyncio.run(awaitable)
    except HTTPException as error:
        return error
    raise AssertionError("Expected HTTPException")


class ServiceHelpersTests(unittest.TestCase):
    def test_error_and_success_payload_helpers(self):
        self.assertEqual(
            service_helpers.error_detail("Bad request", details="missing", code="BAD_REQUEST"),
            {"error": "Bad request", "details": "missing", "code": "BAD_REQUEST"},
        )

        self.assertEqual(
            service_helpers.success_payload(
                "OK",
                {"token": "abc"},
                include_root_fields=True,
                extra_value=1,
            ),
            {
                "message": "OK",
                "data": {"token": "abc"},
                "token": "abc",
                "extra_value": 1,
            },
        )

    def test_exception_is(self):
        self.assertTrue(service_helpers.exception_is(ValueError)(ValueError("bad")))
        self.assertFalse(service_helpers.exception_is(ValueError)(RuntimeError("bad")))

    def test_require_teacher_enforces_permission(self):
        service_helpers.require_teacher({"user_id": "teacher-1"}, "forbidden", lambda _user_id: True)
        with self.assertRaises(HTTPException) as ctx:
            service_helpers.require_teacher({"user_id": "student-1"}, "forbidden", lambda _user_id: False)
        self.assertEqual(ctx.exception.status_code, 403)

        service_helpers.require_allowed(True)
        with self.assertRaises(HTTPException) as ctx:
            service_helpers.require_allowed(False, "blocked")
        self.assertEqual(ctx.exception.detail, "blocked")

    def test_run_service_maps_rule_and_fallback(self):
        async def run_http_exception():
            return await service_helpers.run_service(
                lambda: (_ for _ in ()).throw(HTTPException(status_code=409, detail="conflict")),
            )

        self.assertEqual(capture_http_exception(run_http_exception()).status_code, 409)

        async def run_value_error():
            return await service_helpers.run_service(
                lambda: (_ for _ in ()).throw(ValueError("bad")),
                error_rules=[(service_helpers.exception_is(ValueError), 400, "Bad request")],
            )

        error = capture_http_exception(run_value_error())
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.detail, "Bad request")

        logger = Mock()

        async def run_runtime_error():
            return await service_helpers.run_service(
                lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                fallback_detail=lambda error: f"Failed: {error}",
                logger=logger,
                log_message="service failed: %s",
            )

        error = capture_http_exception(run_runtime_error())
        self.assertEqual(error.status_code, 500)
        self.assertEqual(error.detail, "Failed: boom")
        logger.error.assert_called_once()

    def test_run_service_maps_service_error(self):
        async def run_not_found():
            return await service_helpers.run_service(
                lambda: (_ for _ in ()).throw(NotFoundError("Missing")),
            )

        error = capture_http_exception(run_not_found())
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.detail, "Missing")

    def test_run_async_service_supports_http_and_fallback(self):
        async def raises_http():
            raise HTTPException(status_code=418, detail="teapot")

        self.assertEqual(capture_http_exception(service_helpers.run_async_service(raises_http)).status_code, 418)

        async def raises_runtime():
            raise ValidationServiceError("Broken")

        error = capture_http_exception(service_helpers.run_async_service(raises_runtime))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.detail, "Broken")

        async def raises_value_error():
            raise ValueError("bad async input")

        error = capture_http_exception(
            service_helpers.run_async_service(
                raises_value_error,
                error_rules=[(service_helpers.exception_is(ValueError), 422, lambda error: str(error))],
            )
        )
        self.assertEqual(error.status_code, 422)
        self.assertEqual(error.detail, "bad async input")
