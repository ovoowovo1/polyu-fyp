"""Annotated fixed cases run the production orchestration; only I/O is deterministic."""
import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.rag import index
from app.services.rag.citation import service
from app.services.rag.retrieval import service as retrieval
from app.services.rag.retrieval import context
from app.services.rag.retrieval.intent import _build_single_query_intent

CASES = json.loads((Path(__file__).resolve().parents[1] / 'evaluation/fixtures/rag_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_production_rag_fixed_evidence_contract(case):
    documents = [{'chunkId': s['chunk_id'], 'fileId': s['file_id'], 'source': s['name'], 'text': s['content'],
        'page': s['page_start'], 'page_end': s['page_end'], 'chunk_index': s['chunk_index']} for s in case['sources']]

    async def llm(prompt, schema, *, operation_name, **kwargs):
        if operation_name == 'Adaptive RAG route and query plan':
            return {'decision': 'retrieve', 'reason': 'course', 'query_intent': _build_single_query_intent(case['question'])}
        if operation_name == 'Adaptive RAG grade document batch':
            return {'grades': [{'chunk_id': d['chunkId'], 'relevance_score': .9, 'reason': 'relevant', 'covered_concepts': []} for d in documents]}
        if operation_name == 'RAG verify':
            if case['scenario'] == 'service_failure':
                raise RuntimeError('verifier unavailable')
            submitted = json.loads(prompt[prompt.index('{'):])['draft']['blocks']
            return {'blocks': [{'id': b['id'], 'supported': case['scenario'] != 'wrong_semantics', 'reason': 'evidence checked'} for b in submitted], 'missing_topics': []}
        answer = copy.deepcopy(case['draft'])
        if operation_name == 'RAG repair' and case['scenario'] == 'repair':
            answer['blocks'][0]['evidence'][0]['quote'] = documents[0]['text']
        return answer

    async def search(state, emit, **kwargs):
        state['candidate_documents'] = documents
        state['missing_concepts'] = []
        return state

    async def run():
        with patch.object(index, 'generate_structured_json', side_effect=llm), \
             patch.object(service, 'generate_structured_json', side_effect=llm), \
             patch.object(retrieval, 'generate_structured_json', side_effect=llm), \
             patch.object(index, 'retrieve_documents_node', side_effect=search), \
             patch.object(context, 'retrieve_adjacent_chunks', return_value=[]):
            return await index.run_rag(case['question'], case['selected_file_ids'], AsyncMock())

    result = asyncio.run(run())
    assert result['status'] == case['expected_status']
    assert [s['chunk_id'] for s in result['sources']] == case['expected_source_ids']
    assert all(s['file_id'] in case['selected_file_ids'] for s in result['sources'])
    source_ids = {s['chunk_id'] for s in result['sources']}
    assert all(set(b['source_ids']) <= source_ids for b in result['blocks'])
    if case['scenario'] == 'normal':
        assert [b['markdown'] for b in result['blocks'][:len(case['draft']['blocks'])]] == [b['markdown'] for b in case['draft']['blocks']]
    if case['expected_status'] == 'unavailable':
        assert not any(b['source_ids'] for b in result['blocks'])
