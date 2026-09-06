from contextlib import contextmanager
from unittest.mock import patch
import unittest
from app.services.rag.retrieval import vector as vector_query_service
from tests.support import make_embedding_settings, make_embedding_error

class SuccessfulQueryModel:
    def __init__(self, model_name, vector):
        self.model_name, self.vector, self.calls = model_name, vector, []
    async def aembed_query(self, text):
        self.calls.append(text)
        return self.vector

@contextmanager
def patched_vector_dependencies(primary_model, *, rows=None):
    with patch.object(vector_query_service, 'get_settings', return_value=make_embedding_settings(redis_cache_enabled=False)), patch.object(vector_query_service, 'get_embedding_model', return_value=primary_model), patch.object(vector_query_service.pg_service, 'retrieve_graph_context', return_value=rows or []) as retrieve, patch('app.services.cache.rag_cache.redis_cache.is_enabled', return_value=False):
        yield retrieve

class VectorQueryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_is_required(self):
        with patched_vector_dependencies(None), self.assertRaises(RuntimeError):
            await vector_query_service.retrieve_vector_context('q', ['f1'])

    async def test_single_model_and_selected_file_scope(self):
        model = SuccessfulQueryModel('google/gemini-embedding-2', [0.1])
        with patched_vector_dependencies(model, rows=[{'chunkId':'c1'}]) as retrieve:
            rows, mode = await vector_query_service.retrieve_vector_context(' hello ', ['f1'], k=5)
        self.assertEqual(mode, 'single')
        self.assertEqual(rows, [{'chunkId':'c1'}])
        self.assertEqual(model.calls, ['hello'])
        retrieve.assert_called_once_with([0.1], 5, ['f1'])

    async def test_failure_propagates_without_switching_model(self):
        from unittest.mock import AsyncMock
        for error in (ValueError('bad input'), make_embedding_error()):
            model = SuccessfulQueryModel('google/gemini-embedding-2', [])
            model.aembed_query = AsyncMock(side_effect=error)
            with patched_vector_dependencies(model) as retrieve, self.assertRaises(type(error)):
                await vector_query_service.retrieve_vector_context('q', ['f1'])
            retrieve.assert_not_called()
