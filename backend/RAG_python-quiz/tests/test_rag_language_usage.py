import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.ai.llm import structured_json
from app.services.rag import index, language
from app.services.rag.citation import service
from app.services.rag.citation.models import AnswerDraft
from app.services.rag.orchestration import routing
from app.services.rag.retrieval import grading
from app.services.rag.retrieval.intent import _build_single_query_intent
from app.services.rag.retrieval.workflow import build_initial_state
from app.utils import model_usage
from tests.support import fake_llm_retry, make_chat_client, make_completion_response


def doc(chunk_id="c1", text="SQL stores data in tables."):
    return {"chunkId": chunk_id, "fileId": "f1", "text": text, "source": "lesson.pdf", "page": 1}


@pytest.mark.parametrize("question,target", [
    ("What is SQL?", "English"), ("甚麼是 SQL？", "Traditional Chinese"),
    ("甚麼是 SQL？Please answer in French.", "French"),
    ("Explain SQL in 日本語", "Japanese"), ("¿Qué es SQL?", "Spanish"),
])
def test_planner_language_is_passed_without_backend_classification(question, target):
    result = {"decision": "retrieve", "reason": "course", "answer_language": target,
              "messages": {"insufficient_evidence": "localized notice"},
              "query_intent": _build_single_query_intent(question)}
    actual = asyncio.run(routing.plan_question(question, generate_structured_json=AsyncMock(return_value=result), logger=Mock()))
    assert actual["answer_language"] == target
    assert "enum" not in routing.build_combined_planner_schema()["properties"]["answer_language"]
    token = language.answer_language.set(actual["answer_language"])
    try:
        assert target in language.instruction(question)
        assert language.language_for(question) == target
    finally:
        language.answer_language.reset(token)


@pytest.mark.parametrize("updates", [{"answer_language": ""}, {"answer_language": None},
                                      {"messages": []}, {"messages": {"omitted_content": ""}}])
def test_invalid_planner_language_falls_back_without_guessing(updates):
    result = {"decision": "retrieve", "reason": "course", "answer_language": "French",
              "query_intent": _build_single_query_intent("Explain SQL"), **updates}
    fallback = asyncio.run(routing.plan_question("Explain SQL", generate_structured_json=AsyncMock(return_value=result), logger=Mock()))
    assert fallback["answer_language"] is None and fallback["messages"] == {}
    assert "original question" in language.instruction("Explain SQL")


def test_prefix_is_reused_and_dynamic_question_and_draft_follow_evidence():
    client = make_chat_client(NS(choices=[NS(message=NS(content='{"ok": true}'), finish_reason="stop")]))
    async def run():
        with patch.object(structured_json, "get_llm_client", return_value=client), \
             patch.object(structured_json, "get_default_llm_model_name", return_value="model"), \
             patch.object(structured_json, "with_llm_retry_async", side_effect=fake_llm_retry):
            for prompt in ['Generate\n{"question":"first", "evidence":[], "feedback":null}',
                           'Verify\n{"question":"second", "evidence":[], "draft":{}}']:
                await structured_json.generate_structured_json(prompt, {"required": ["ok"]},
                    operation_name="test", system_prompt="common instructions",
                    evidence_prefix=[{"chunk_id": "c1", "content": "原文證據"}], task_instruction="Answer in French")
    asyncio.run(run())
    first, second = [call.kwargs["messages"] for call in client.chat.completions.create.call_args_list]
    assert first[:2] == second[:2] and first[2] != second[2]
    assert "原文證據" in first[1]["content"]
    assert "原文證據" not in first[2]["content"] and "Answer in French" in first[2]["content"]


def test_paid_response_is_recorded_even_when_json_parsing_fails():
    reply = NS(choices=[NS(message=NS(content="invalid JSON"), finish_reason="stop")])
    reply.usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    client = make_chat_client(reply)
    async def run():
        with model_usage.usage_scope("parse-failure") as session, model_usage.operation_scope("json"), \
             patch.object(structured_json, "get_llm_client", return_value=client), \
             patch.object(structured_json, "get_default_llm_model_name", return_value="model"), \
             patch.object(structured_json, "with_llm_retry_async", side_effect=fake_llm_retry):
            with pytest.raises(RuntimeError):
                await structured_json.generate_structured_json("prompt", {}, operation_name="json")
        return session
    session = asyncio.run(run())
    assert [r["attempt"] for r in session.records] == [1, 2]
    assert model_usage.aggregate(session.records)["total_tokens"] == 24


def test_same_evidence_language_used_in_generate_verify_and_repair():
    draft = {"blocks": [], "limitations": ["Pas assez de preuves."]}
    calls = []
    async def llm(prompt, schema, **kwargs):
        calls.append((prompt, kwargs))
        return {"blocks": [{"id": "limitation:0", "supported": True, "reason": "Correct"}], "missing_topics": []} if kwargs['operation_name'] == 'RAG verify' else draft
    async def run():
        token = language.answer_language.set("French")
        try:
            with patch.object(service, "generate_structured_json", side_effect=llm):
                answer = await service.generate_answer("Explain SQL in French", [doc(text="中文來源")])
                await service.verify_answer("Explain SQL in French", answer, [doc(text="中文來源")], ["f1"])
                await service.generate_answer("Explain SQL in French", [doc(text="中文來源")], feedback={"errors": {}})
        finally:
            language.answer_language.reset(token)
    asyncio.run(run())
    assert all('French' in kwargs['task_instruction'] for _, kwargs in calls)
    assert calls[0][1]['evidence_prefix'] == calls[1][1]['evidence_prefix'] == calls[2][1]['evidence_prefix']
    assert 'wrong answer language' in calls[1][0]


def test_valid_partial_answer_does_not_trigger_extra_generation():
    planner = {'decision': 'retrieve', 'answer_language': 'French', 'messages': {}, 'query_intent': _build_single_query_intent('SQL?')}
    answer = AnswerDraft.model_validate({'blocks': [{'id': 'b1', 'markdown': 'SQL utilise des tables.', 'kind': 'factual',
        'evidence': [{'chunk_id': 'c1', 'quote': 'SQL stores data in tables.'}]}], 'limitations': ['Version non précisée.']})
    async def search(state, emit):
        state.update(candidate_documents=[doc()], filtered_documents=[doc()], grading_failed=False, missing_concepts=[])
        return state
    async def run():
        with patch.object(index, 'plan_question', AsyncMock(return_value=planner)), \
             patch.object(index, 'retrieve_documents_node', side_effect=search), \
             patch.object(index, 'grade_documents_node', side_effect=search), \
             patch.object(index, 'build_context', AsyncMock(return_value=[doc()])), \
             patch.object(index, 'generate_answer', AsyncMock(return_value=answer)) as generate, \
             patch.object(index, 'verify_answer', AsyncMock(return_value=(NS(missing_topics=[]), {}))) as verify:
            result = await index.run_rag('SQL?', ['f1'], AsyncMock())
        assert generate.await_count == verify.await_count == 1
        assert result['status'] == 'partial' and result['blocks'][0]['markdown'] == 'SQL utilise des tables.'
        assert language.answer_language.get() is None and language.system_messages.get() is None
    asyncio.run(run())


def test_grading_cache_reuses_only_identical_decisions():
    async def run():
        state = build_initial_state('SQL?', ['f1'], _build_single_query_intent('SQL?'))
        state['candidate_documents'] = [doc()]
        batches = []
        async def llm(prompt, schema, **kwargs):
            ids = schema['properties']['grades']['items']['properties']['chunk_id']['enum']
            batches.append(ids)
            return {'grades': [{'chunk_id': i, 'relevance_score': .9, 'covered_concepts': [], 'reason': 'relevant'} for i in ids]}
        async def grade():
            return await grading.grade_documents_node(state, AsyncMock(), log_prefix='test', generate_structured_json_func=llm)
        await grade()
        await grade()
        assert batches == [['c1']]
        state['candidate_documents'] = [doc(), doc('c2')]
        await grade()
        assert batches[-1] == ['c2']
        state['candidate_documents'] = [doc(text='Changed content')]
        await grade()
        assert batches[-1] == ['c1'] and len(batches) == 3
        state['query_intent']['required_concepts'] = ['new concept']
        await grade()
        assert len(batches) == 4
        state['candidate_documents'][0]['image_data'] = 'data:image/png;base64,new'
        await grade()
        assert len(batches) == 5
    asyncio.run(run())
