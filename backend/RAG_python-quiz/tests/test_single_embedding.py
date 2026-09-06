import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from app.services.documents import document_service as documents
from app.utils.runtime.embedding_provider_response import build_embedding_request, collect_embeddings
from app.utils.api_key_manager import OpenAIEmbeddings
from tests.support import make_embedding_settings


def image(i):
    return {"content": [{"type": "image_url", "image_url": {"url": str(i)}}]}


def test_mixed_batches_restore_chunk_positions_and_page_metadata():
    inputs = [str(i) for i in range(42)]
    for i in (6, 10, 11, 12, 13, 14, 15):
        inputs[i] = image(i)
    calls = []
    async def embed(batch, *args, **kwargs):
        calls.append(batch)
        return [[float(x["content"][0]["image_url"]["url"] if isinstance(x, dict) else x)] for x in batch]
    chunks = [{"pageContent": str(i), "embeddingInput": value, "metadata": {"pageNumber": i // 3 + 1}} for i, value in enumerate(inputs)]
    with patch.object(documents, 'create_embedding_model', return_value=object()) as create, patch.object(documents, '_embed_batch_with_adaptive_retry', side_effect=embed):
        vectors = asyncio.run(documents._embed_chunks_for_storage(chunks))
    assert vectors == [[float(i)] for i in range(42)]
    assert [len(batch) for batch in calls] == [30, 5, 6, 1]
    assert all(all(isinstance(x, type(batch[0])) for x in batch) for batch in calls)
    assert create.call_count == 1
    rows = documents._assemble_chunks_for_db(chunks, vectors)
    assert all(row['embedding'] == [float(i)] and row['metadata']['pageNumber'] == i // 3 + 1 for i, row in enumerate(rows))


def test_missing_batch_vectors_fail_before_storage():
    with patch.object(documents, '_embed_batch_with_adaptive_retry', AsyncMock(return_value=[])), pytest.raises(ValueError):
        asyncio.run(documents.embed_texts_with_retry(['text'], embeddings_model=object()))


@pytest.mark.parametrize('value', [[], None, 4, ['ok', image(1)], [''], [{"content": []}], [{"content": ['bad']}], [{"content": [{"type": "image_url", "image_url": {"url": 3}}]}]])
def test_invalid_input_is_rejected_without_provider_call(value):
    with pytest.raises(ValueError):
        build_embedding_request('key', 'google/gemini-embedding-2', value)


def test_request_dimensions_and_homogeneous_images():
    for value in (['text'], [image(1)]):
        payload, _ = build_embedding_request('key', 'google/gemini-embedding-2', value)
        assert payload['dimensions'] == 3072 and payload['input'] == value


def fail(**kwargs):
    assert kwargs['retryable'] is False
    raise ValueError(kwargs['message'])


@pytest.mark.parametrize('data', [[], [{}], [{'index': True}], [{'index': -1}], [{'index': 1}], [{'index': 0}, {'index': 0}], [{'index': 0, 'embedding': [0.0]}], [{'index': 0, 'embedding': [float('nan')] * 3072}], [{'index': 0, 'embedding': [float('inf')] * 3072}], [{'index': 0, 'embedding': [True] * 3072}], [{'index': 0, 'embedding': ['0'] * 3072}]])
def test_response_requires_complete_indices_and_finite_vectors(data):
    with pytest.raises(ValueError):
        collect_embeddings(SimpleNamespace(status_code=200), data, 1, '', fail)


def test_out_of_order_provider_vectors_are_restored():
    vectors = [[0.0] * 3072, [1.0] * 3072]
    assert collect_embeddings(SimpleNamespace(status_code=200), [{'index': 1, 'embedding': vectors[1]}, {'index': 0, 'embedding': vectors[0]}], 2, '', fail) == vectors


def test_other_models_are_rejected():
    with patch('app.utils.api_key_manager.get_settings', return_value=make_embedding_settings()), pytest.raises(ValueError, match='Only google/gemini-embedding-2'):
        OpenAIEmbeddings(model_name='unsupported-model')
