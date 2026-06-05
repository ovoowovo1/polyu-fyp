import unittest
from unittest.mock import patch

from app.routers import classes
from tests.support import build_authed_client


class ClassesApiTests(unittest.TestCase):
    def setUp(self):
        _app, self.client = build_authed_client(
            classes.router,
            classes.get_current_user,
            {"user_id": "teacher-1", "email": "t@example.com"},
        )

    def route(self, method, path, service_name, *, status=200, return_value=None, side_effect=None, json=None):
        patch_kwargs = {"side_effect": side_effect} if side_effect is not None else {"return_value": return_value}
        with patch(f"app.routers.classes.pg_service.{service_name}", **patch_kwargs):
            request = getattr(self.client, method)
            response = request(path, json=json) if json is not None else request(path)

        self.assertEqual(response.status_code, status)
        return response

    def test_create_class_success(self):
        response = self.route(
            "post",
            "/classes/",
            "create_class_for_teacher",
            status=201,
            return_value={"id": "class-1", "name": "DB"},
            json={"name": "DB"},
        )
        self.assertEqual(response.json()["class"]["id"], "class-1")

    def test_list_my_classes_success(self):
        response = self.route("get", "/classes/mine", "list_classes_by_teacher", return_value=[{"id": "class-1"}])
        self.assertEqual(response.json()["total"], 1)

    def test_list_enrolled_classes_success(self):
        response = self.route("get", "/classes/enrolled", "list_classes_for_student", return_value=[{"id": "class-1"}])
        self.assertEqual(response.json()["total"], 1)

    def test_invite_student_success(self):
        response = self.route(
            "post",
            "/classes/class-1/invite",
            "invite_student_to_class",
            return_value={"id": "enroll-1"},
            json={"email": "student@example.com"},
        )
        self.assertEqual(response.json()["enrollment"]["id"], "enroll-1")

    def test_service_errors_return_expected_status(self):
        create_json = {"name": "DB"}
        invite_json = {"email": "student@example.com"}
        cases = (
            ("post", "/classes/", "create_class_for_teacher", PermissionError("teachers only"), 403, "teachers only", create_json),
            ("post", "/classes/", "create_class_for_teacher", RuntimeError("bad request"), 400, "bad request", create_json),
            ("post", "/classes/", "create_class_for_teacher", Exception("boom"), 500, "Failed to create class", create_json),
            ("get", "/classes/mine", "list_classes_by_teacher", PermissionError("forbidden"), 403, "forbidden", None),
            ("get", "/classes/mine", "list_classes_by_teacher", Exception("db"), 500, "Failed to fetch classes", None),
            ("get", "/classes/enrolled", "list_classes_for_student", PermissionError("forbidden"), 403, "forbidden", None),
            ("get", "/classes/enrolled", "list_classes_for_student", Exception("db"), 500, "Failed to fetch enrolled classes", None),
            ("post", "/classes/class-1/invite", "invite_student_to_class", PermissionError("forbidden"), 403, "forbidden", invite_json),
            ("post", "/classes/class-1/invite", "invite_student_to_class", RuntimeError("duplicate"), 400, "duplicate", invite_json),
            ("post", "/classes/class-1/invite", "invite_student_to_class", Exception("db"), 500, "Failed to invite student", invite_json),
        )
        for method, path, service_name, side_effect, status, error, payload in cases:
            with self.subTest(path=path, error=error):
                response = self.route(method, path, service_name, side_effect=side_effect, status=status, json=payload)
                self.assertEqual(response.json()["detail"]["error"], error)
