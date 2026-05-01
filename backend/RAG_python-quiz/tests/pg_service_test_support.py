import unittest
from datetime import datetime
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from tests.support import FakeConnection, FakeCursor


class FixedDateTime(datetime):
    @classmethod
    def now(cls):
        return cls(2025, 1, 2, 3, 4, 5)


class PgServiceBase(unittest.TestCase):
    module_path = ""

    @contextmanager
    def _patch_exam_service_split(self, cursor: FakeCursor):
        modules = [
            "app.services.pg_exam_crud",
            "app.services.pg_exam_submission_service",
            "app.services.pg_exam_grading_service",
        ]
        with ExitStack() as stack:
            for module in modules:
                stack.enter_context(patch(f"{module}._get_conn", return_value=FakeConnection(cursor)))
            yield

    def patch_conn(self, cursor: FakeCursor, module_path: str | None = None):
        target = module_path or self.module_path
        if target == "app.services.pg_exam_service":
            return self._patch_exam_service_split(cursor)
        return patch(f"{target}._get_conn", return_value=FakeConnection(cursor))
