import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.services.ai.llm import structured_json
from app.services.rag import index
from app.services.rag.citation import service
from app.services.rag.citation.models import AnswerDraft
from app.utils import model_usage
from tests.support import fake_llm_retry, make_chat_client
from tests.test_adaptive_rag_service import patches
from tests.test_citation_evidence_service import doc, draft, verdict


def test_omitted_heading_evidence_preserves_answer_without_extra_call():
    raw = draft().model_dump()
    raw['blocks'].insert(0, {'id': 'heading', 'kind': 'structural', 'markdown': '## Exam arrangement'})
    verification = {'blocks': [
        {'id': block['id'], 'supported': True, 'reason': 'supported'} for block in raw['blocks']
    ], 'missing_topics': []}
    async def run():
        with patches(), patch.object(index, 'generate_answer', service.generate_answer), \
             patch.object(index, 'verify_answer', service.verify_answer), \
             patch.object(service, 'generate_structured_json', AsyncMock(side_effect=[raw, verification])) as llm:
            result = await index.run_rag('Exam arrangement?', ['f1'], AsyncMock())
        assert llm.await_count == 2
        assert [call.kwargs['operation_name'] for call in llm.call_args_list] == ['RAG generate', 'RAG verify']
        assert 'evidence: []' in llm.call_args_list[0].args[0]
        assert result['status'] == 'complete'
        assert result['blocks'][0] == {'id': 'heading', 'markdown': '## Exam arrangement', 'source_ids': []}
        assert result['blocks'][1]['source_ids'] == ['c1']
    asyncio.run(run())


@pytest.mark.parametrize('evidence', [None, {}, 'c1', [None], [{'chunk_id': 'c1'}]])
def test_only_omission_defaults_to_empty(evidence):
    raw = draft().model_dump()
    raw['blocks'][0]['evidence'] = evidence
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate(raw)


def test_missing_factual_evidence_and_invalid_sources_remain_unsupported():
    raw = draft().model_dump()
    del raw['blocks'][0]['evidence']
    answer = AnswerDraft.model_validate(raw)
    assert answer.blocks[0].evidence == []
    assert 'b1' in service.check_structure(answer, [doc()], ['f1'])
    assert 'b1' in service.check_structure(draft(source='unknown'), [doc()], ['f1'])
    assert 'b1' in service.check_structure(draft(quote='Invented quote'), [doc()], ['f1'])


def test_factual_claim_disguised_as_heading_is_rejected_by_verifier():
    raw = draft(markdown='## The exam is tomorrow').model_dump()
    raw['blocks'][0]['kind'] = 'structural'
    del raw['blocks'][0]['evidence']
    answer = AnswerDraft.model_validate(raw)
    async def run():
        with patch.object(service, 'generate_structured_json', AsyncMock(return_value=verdict(False).model_dump())) as llm:
            _, errors = await service.verify_answer('Exam date?', answer, [doc()], ['f1'])
        assert 'Structural blocks are supported only if they contain no factual' in llm.call_args.args[0]
        assert 'b1' in errors
        result = service.result_payload(answer, [doc()], errors, [], 'trace', 'Exam date?')
        assert 'The exam is tomorrow' not in str(result)
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['generation', 'answer_parsing', 'evidence_verification', 'repair', 'repair_parsing', 'repair_verification'])
def test_safe_failure_stage_logs(phase, caplog):
    raw = draft(markdown='PRIVATE DOCUMENT CONTENT').model_dump()
    raw['blocks'][0]['evidence'] = None
    try:
        AnswerDraft.model_validate(raw)
    except ValidationError as error:
        validation_error = error
    failure = validation_error if 'parsing' in phase or phase == 'repair_verification' else RuntimeError('PRIVATE DOCUMENT CONTENT')
    async def run():
        with patches():
            if phase.startswith('repair'):
                index.verify_answer.side_effect = [(verdict(), {'b1': 'unsupported'}), failure]
                if phase != 'repair_verification':
                    index.generate_answer.side_effect = [draft(), failure]
            elif phase == 'evidence_verification':
                index.verify_answer.side_effect = failure
            else:
                index.generate_answer.side_effect = failure
            return await index.run_rag('q', ['f1'], AsyncMock())
    result = asyncio.run(run())
    assert result['status'] == 'unavailable'
    assert f"trace_id={result['trace_id']} stage={phase}" in caplog.text
    assert 'PRIVATE DOCUMENT CONTENT' not in caplog.text
    if isinstance(failure, ValidationError):
        assert "('blocks', 0, 'evidence')" in caplog.text
        assert 'error_type=ValidationError' in caplog.text


def test_usage_survives_answer_schema_failure_without_extra_generation():
    raw = draft().model_dump()
    raw['blocks'][0]['evidence'] = None
    reply = NS(choices=[NS(message=NS(content=json.dumps(raw)), finish_reason='stop')],
               usage={'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12})
    client = make_chat_client(reply)
    async def run():
        with model_usage.usage_scope('schema-failure') as session, \
             patch.object(structured_json, 'get_llm_client', return_value=client), \
             patch.object(structured_json, 'get_default_llm_model_name', return_value='model'), \
             patch.object(structured_json, 'with_llm_retry_async', side_effect=fake_llm_retry):
            with pytest.raises(ValidationError):
                await service.generate_answer('q', [doc()])
        assert len(session.records) == client.chat.completions.create.call_count == 1
        assert model_usage.aggregate(session.records)['total_tokens'] == 12
    asyncio.run(run())


def test_invalid_json_does_not_expose_response_content():
    with pytest.raises(RuntimeError) as failure:
        structured_json._parse_structured_json_text('PRIVATE DOCUMENT CONTENT', 'RAG generate')
    assert 'PRIVATE DOCUMENT CONTENT' not in str(failure.value)
    assert 'line 1, column 1' in str(failure.value)
