import unittest

from app.services import pg_service
from app.services import pg_classes_service, pg_exam_service, pg_files_service, pg_quiz_service, pg_retrieval_service, pg_shared


class PgServiceFacadeTests(unittest.TestCase):
    def test_facade_re_exports_public_domain_functions(self):
        self.assertIs(pg_service._to_pgvector, pg_shared._to_pgvector)
        self.assertIs(pg_service.find_document_by_hash, pg_retrieval_service.find_document_by_hash)
        self.assertIs(pg_service.get_files_list, pg_files_service.get_files_list)
        self.assertIs(pg_service.save_quiz, pg_quiz_service.save_quiz)
        self.assertIs(pg_service.is_user_teacher, pg_classes_service.is_user_teacher)
        self.assertIs(pg_service.save_exam, pg_exam_service.save_exam)
