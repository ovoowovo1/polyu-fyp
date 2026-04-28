import unittest
from datetime import datetime
from unittest.mock import patch

from tests.support import FakeConnection, FakeCursor


class FixedDateTime(datetime):
    @classmethod
    def now(cls):
        return cls(2025, 1, 2, 3, 4, 5)


class PgServiceBase(unittest.TestCase):
    module_path = ""

    def patch_conn(self, cursor: FakeCursor, module_path: str | None = None):
        target = module_path or self.module_path
        return patch(f"{target}._get_conn", return_value=FakeConnection(cursor))
