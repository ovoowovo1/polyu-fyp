from types import SimpleNamespace
import unittest

from app.services.cache import studio_cache


class StudioCacheTests(unittest.TestCase):
    def test_namespaces_are_stable(self):
        self.assertEqual(studio_cache.classes_user_namespace("user-1"), "classes:user:user-1")
        self.assertEqual(studio_cache.quiz_list_namespace(), "quiz:list")
        self.assertEqual(studio_cache.quiz_detail_namespace("quiz-1"), "quiz:detail:quiz-1")
        self.assertEqual(studio_cache.exam_list_namespace(), "exam:list")
        self.assertEqual(studio_cache.exam_detail_namespace("exam-1"), "exam:detail:exam-1")
        self.assertEqual(studio_cache.files_list_namespace(), "files:list")
        self.assertEqual(studio_cache.file_detail_namespace("file-1"), "files:detail:file-1")
        self.assertEqual(studio_cache.chunk_source_namespace(), "chunks:source-details")
        self.assertEqual(studio_cache.rag_retrieval_namespace(), "rag:retrieval")

    def test_can_use_cache_returns_false_when_checker_fails(self):
        self.assertTrue(studio_cache.can_use_cache(lambda user_id, item_id: user_id == "u" and item_id == "i", "u", "i"))

        def broken_checker():
            raise RuntimeError("db down")

        self.assertFalse(studio_cache.can_use_cache(broken_checker))

    def test_id_from_result_supports_dicts_and_objects(self):
        self.assertEqual(studio_cache.id_from_result({"exam_id": "exam-1"}, "exam_id", "id"), "exam-1")
        self.assertEqual(studio_cache.id_from_result({"id": "exam-2"}, "exam_id", "id"), "exam-2")
        self.assertEqual(studio_cache.id_from_result(SimpleNamespace(exam_id="exam-3"), "exam_id", "id"), "exam-3")
        self.assertEqual(studio_cache.id_from_result(SimpleNamespace(id="exam-4"), "exam_id", "id"), "exam-4")
        self.assertEqual(studio_cache.id_from_result({}, "exam_id", "id"), "")
        self.assertEqual(studio_cache.id_from_result(SimpleNamespace(), "exam_id", "id"), "")
