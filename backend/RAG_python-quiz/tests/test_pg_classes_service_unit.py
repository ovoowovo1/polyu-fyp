from datetime import datetime
from unittest.mock import patch

from app.services import pg_service
from tests.pg_service_test_support import PgServiceBase
from tests.support import FakeCursor


class PgClassesServiceTests(PgServiceBase):
    module_path = "app.services.pg_classes_service"

    def test_is_user_teacher_and_class_creation_cover_validation_and_success(self):
        with self.patch_conn(FakeCursor(fetchone_results=[{"role": "teacher"}])):
            self.assertTrue(pg_service.is_user_teacher("teacher-1"))

        with self.patch_conn(FakeCursor(fetchone_results=[{"role": "student"}])):
            self.assertFalse(pg_service.is_user_teacher("student-1"))

        with self.assertRaises(RuntimeError):
            pg_service.create_class_for_teacher("teacher-1", "")

        with patch("app.services.pg_classes_service.is_user_teacher", return_value=False):
            with self.assertRaises(PermissionError):
                pg_service.create_class_for_teacher("teacher-1", "Class")

        row = {"id": "class-1", "teacher_id": "teacher-1", "name": "Databases", "code": "DB01", "created_at": datetime(2025, 1, 2, 3, 4, 5)}
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(FakeCursor(fetchone_results=[row])):
            created = pg_service.create_class_for_teacher("teacher-1", " Databases ", code="DB01")
        self.assertEqual(created["name"], "Databases")

    def test_class_listing_and_student_helpers_cover_success_and_error_paths(self):
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=False):
            with self.assertRaises(PermissionError):
                pg_service.list_classes_by_teacher("teacher-1")

        created_at = datetime(2025, 1, 2, 3, 4, 5)
        row = {
            "id": "class-1",
            "teacher_id": "teacher-1",
            "name": "Databases",
            "code": "DB01",
            "created_at": created_at,
            "student_count": 1,
            "students": [{"id": "student-1", "name": "Student", "email": "s@example.com"}],
        }
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(FakeCursor(fetchall_results=[[row]])):
            classes = pg_service.list_classes_by_teacher("teacher-1")
        self.assertEqual(classes[0]["student_count"], 1)

        cursor = FakeCursor(fetchone_results=[{"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"}, {"exists": 1}, {"exists": 1}], fetchall_results=[[row]])
        self.assertEqual(pg_service._get_user_by_email(cursor, "s@example.com")["email"], "s@example.com")
        self.assertTrue(pg_service._is_student_exists(cursor, "student-1"))
        self.assertTrue(pg_service._is_class_owned_by_teacher(cursor, "class-1", "teacher-1"))

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(PermissionError):
                pg_service.list_classes_for_student("student-1")

        list_row = {"id": "class-1", "teacher_id": "teacher-1", "name": "Databases", "code": None, "created_at": created_at, "student_count": 2}
        cursor = FakeCursor(fetchone_results=[{"exists": 1}], fetchall_results=[[list_row]])
        with self.patch_conn(cursor):
            classes = pg_service.list_classes_for_student("student-1")
        self.assertEqual(classes[0]["student_count"], 2)

    def test_invite_student_to_class_covers_validation_and_conflict_lookup(self):
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=False):
            with self.assertRaises(PermissionError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "")

        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(PermissionError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        cursor = FakeCursor(fetchone_results=[{"ok": 1}, None])
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        cursor = FakeCursor(fetchone_results=[{"ok": 1}, {"id": "teacher-2", "email": "t@example.com", "full_name": "Teacher", "role": "teacher"}])
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "t@example.com")

        cursor = FakeCursor(fetchone_results=[{"ok": 1}, {"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"}, None])
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        cursor = FakeCursor(
            fetchone_results=[
                {"ok": 1},
                {"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"},
                {"exists": 1},
                {"class_id": "class-1", "student_id": "student-1", "enrolled_at": datetime(2025, 1, 2, 3, 4, 5)},
            ]
        )
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            invited = pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")
        self.assertEqual(invited["student"]["email"], "s@example.com")

        cursor = FakeCursor(
            fetchone_results=[
                {"ok": 1},
                {"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"},
                {"exists": 1},
                None,
                {"class_id": "class-1", "student_id": "student-1", "enrolled_at": None},
            ]
        )
        with patch("app.services.pg_classes_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            invited = pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")
        self.assertEqual(invited["student_id"], "student-1")
