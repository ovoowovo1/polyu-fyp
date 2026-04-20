import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.routers import classes
from tests.support import build_app, with_auth


class ClassesApiTests(unittest.TestCase):
    def setUp(self):
        app = build_app(classes.router)
        with_auth(app, classes.get_current_user, {"user_id": "teacher-1", "email": "t@example.com"})
        self.client = TestClient(app)

    def test_create_class_success(self):
        with patch("app.routers.classes.pg_service.create_class_for_teacher", return_value={"id": "class-1", "name": "DB"}):
            response = self.client.post("/classes/", json={"name": "DB"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["class"]["id"], "class-1")

    def test_create_class_permission_error(self):
        with patch("app.routers.classes.pg_service.create_class_for_teacher", side_effect=PermissionError("teachers only")):
            response = self.client.post("/classes/", json={"name": "DB"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["error"], "teachers only")

    def test_create_class_runtime_error(self):
        with patch("app.routers.classes.pg_service.create_class_for_teacher", side_effect=RuntimeError("bad request")):
            response = self.client.post("/classes/", json={"name": "DB"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "bad request")

    def test_create_class_unexpected_error(self):
        with patch("app.routers.classes.pg_service.create_class_for_teacher", side_effect=Exception("boom")):
            response = self.client.post("/classes/", json={"name": "DB"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["error"], "Failed to create class")

    def test_list_my_classes_success(self):
        with patch("app.routers.classes.pg_service.list_classes_by_teacher", return_value=[{"id": "class-1"}]):
            response = self.client.get("/classes/mine")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)

    def test_list_my_classes_permission_error(self):
        with patch("app.routers.classes.pg_service.list_classes_by_teacher", side_effect=PermissionError("forbidden")):
            response = self.client.get("/classes/mine")

        self.assertEqual(response.status_code, 403)

    def test_list_my_classes_unexpected_error(self):
        with patch("app.routers.classes.pg_service.list_classes_by_teacher", side_effect=Exception("db")):
            response = self.client.get("/classes/mine")

        self.assertEqual(response.status_code, 500)

    def test_list_enrolled_classes_success(self):
        with patch("app.routers.classes.pg_service.list_classes_for_student", return_value=[{"id": "class-1"}]):
            response = self.client.get("/classes/enrolled")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)

    def test_list_enrolled_classes_permission_error(self):
        with patch("app.routers.classes.pg_service.list_classes_for_student", side_effect=PermissionError("forbidden")):
            response = self.client.get("/classes/enrolled")

        self.assertEqual(response.status_code, 403)

    def test_list_enrolled_classes_unexpected_error(self):
        with patch("app.routers.classes.pg_service.list_classes_for_student", side_effect=Exception("db")):
            response = self.client.get("/classes/enrolled")

        self.assertEqual(response.status_code, 500)

    def test_invite_student_success(self):
        with patch("app.routers.classes.pg_service.invite_student_to_class", return_value={"id": "enroll-1"}):
            response = self.client.post("/classes/class-1/invite", json={"email": "student@example.com"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["enrollment"]["id"], "enroll-1")

    def test_invite_student_permission_error(self):
        with patch("app.routers.classes.pg_service.invite_student_to_class", side_effect=PermissionError("forbidden")):
            response = self.client.post("/classes/class-1/invite", json={"email": "student@example.com"})

        self.assertEqual(response.status_code, 403)

    def test_invite_student_runtime_error(self):
        with patch("app.routers.classes.pg_service.invite_student_to_class", side_effect=RuntimeError("duplicate")):
            response = self.client.post("/classes/class-1/invite", json={"email": "student@example.com"})

        self.assertEqual(response.status_code, 400)

    def test_invite_student_unexpected_error(self):
        with patch("app.routers.classes.pg_service.invite_student_to_class", side_effect=Exception("db")):
            response = self.client.post("/classes/class-1/invite", json={"email": "student@example.com"})

        self.assertEqual(response.status_code, 500)
