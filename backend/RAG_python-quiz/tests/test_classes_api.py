import unittest
from unittest.mock import AsyncMock, patch

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

    def test_list_my_classes_uses_cache_when_enabled_and_role_valid(self):
        with patch("app.routers.classes.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.classes.pg_service.is_user_teacher",
            return_value=True,
        ), patch("app.routers.classes.pg_service.list_classes_by_teacher") as list_classes, patch(
            "app.routers.classes.redis_cache.get_or_set_json_with_status",
            AsyncMock(return_value=classes.redis_cache.CacheResult({"classes": [{"id": "class-1"}], "total": 1}, "HIT", "classes:mine")),
        ) as get_or_set:
            response = self.client.get("/classes/mine")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.headers["X-Redis-Cache"], "HIT")
        self.assertEqual(response.headers["X-Redis-Cache-Scope"], "classes:mine")
        list_classes.assert_not_called()
        self.assertEqual(get_or_set.call_args.args[0], "classes:mine")

    def test_list_my_classes_skips_cache_when_role_check_fails(self):
        with patch("app.routers.classes.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.classes.pg_service.is_user_teacher",
            side_effect=RuntimeError("role db"),
        ), patch(
            "app.routers.classes.pg_service.list_classes_by_teacher",
            return_value=[{"id": "class-1"}],
        ), patch("app.routers.classes.redis_cache.get_or_set_json_with_status", AsyncMock()) as get_or_set:
            response = self.client.get("/classes/mine")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "BYPASS")
        get_or_set.assert_not_called()

    def test_list_enrolled_classes_success(self):
        response = self.route("get", "/classes/enrolled", "list_classes_for_student", return_value=[{"id": "class-1"}])
        self.assertEqual(response.json()["total"], 1)

    def test_list_enrolled_classes_uses_cache_when_enabled_and_role_valid(self):
        with patch("app.routers.classes.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.classes.pg_service.is_user_student",
            return_value=True,
        ), patch("app.routers.classes.pg_service.list_classes_for_student") as list_classes, patch(
            "app.routers.classes.redis_cache.get_or_set_json_with_status",
            AsyncMock(return_value=classes.redis_cache.CacheResult({"classes": [{"id": "class-1"}], "total": 1}, "MISS", "classes:enrolled")),
        ) as get_or_set:
            response = self.client.get("/classes/enrolled")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "MISS")
        self.assertEqual(response.headers["X-Redis-Cache-Scope"], "classes:enrolled")
        list_classes.assert_not_called()
        self.assertEqual(get_or_set.call_args.args[0], "classes:enrolled")

    def test_invite_student_success(self):
        response = self.route(
            "post",
            "/classes/class-1/invite",
            "invite_student_to_class",
            return_value={"id": "enroll-1"},
            json={"email": "student@example.com"},
        )
        self.assertEqual(response.json()["enrollment"]["id"], "enroll-1")

    def test_class_mutations_invalidate_user_cache_namespaces(self):
        with patch("app.routers.classes.pg_service.create_class_for_teacher", return_value={"id": "class-1"}), patch(
            "app.routers.classes.redis_cache.invalidate_namespaces"
        ) as invalidate:
            self.client.post("/classes/", json={"name": "DB"})
        invalidate.assert_called_with("classes:user:teacher-1")

        with patch(
            "app.routers.classes.pg_service.invite_student_to_class",
            return_value={"student": {"id": "student-1"}},
        ), patch("app.routers.classes.redis_cache.invalidate_namespaces") as invite_invalidate:
            self.client.post("/classes/class-1/invite", json={"email": "student@example.com"})
        invite_invalidate.assert_called_with("classes:user:teacher-1", "classes:user:student-1")

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
