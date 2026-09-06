import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.rag import index
from app.services.rag.orchestration import routing
from app.services.rag.retrieval.intent import _build_single_query_intent
from tests.test_citation_evidence_service import doc, draft, verdict


def planner():
    return {"decision": "retrieve", "reason": "course", "query_intent": _build_single_query_intent("q")}


async def retrieved(state, emit, **kwargs):
    state["candidate_documents"] = [doc()]
    await emit("retrieved", 1, "retrieval")
    return state


async def graded(state, emit, **kwargs):
    state["filtered_documents"] = list(state["candidate_documents"])
    state["grading_failed"] = False
    return state


def patches():
    return patch.multiple(index, plan_question=AsyncMock(return_value=planner()),
        retrieve_documents_node=AsyncMock(side_effect=retrieved), grade_documents_node=AsyncMock(side_effect=graded),
        retry_missing_concepts_node=AsyncMock(side_effect=retrieved),
        build_context=AsyncMock(return_value=[doc()]), generate_answer=AsyncMock(return_value=draft()),
        verify_answer=AsyncMock(return_value=(verdict(), {})))


def test_stream_final_contract_and_trace():
    async def run():
        with patches():
            events = [e async for e in index.run_adaptive_rag_stream(" q ", ["f1"])]
            trace = {}
            result = await index.run_rag("q", ["f1"], AsyncMock(), trace=trace)
        assert events[0]["type"] == "retrieval"
        assert events[-1]["status"] == "complete"
        assert set(events[-1]) == {"type", "status", "blocks", "sources", "limitations", "trace_id"}
        assert result["trace_id"] == trace["trace_id"]
        assert trace["latency_seconds"] >= 0
        assert [s["stage"] for s in trace["stages"]] == ["retrieved", "graded", "context", "cited"]
    asyncio.run(run())


@pytest.mark.parametrize("case", ["empty", "reject", "no_docs", "grade_failed", "verifier_failed", "retry_grade_failed"])
def test_unavailable_never_releases_draft(case):
    async def run():
        with patches():
            files = ["f1"]
            if case == "empty":
                files = []
            if case == "reject":
                index.plan_question.return_value = planner() | {"decision": "reject"}
            if case == "no_docs":
                index.build_context.return_value = []
            if case in {"grade_failed", "retry_grade_failed"}:
                async def fail(state, emit):
                    state = await graded(state, emit)
                    state["grading_failed"] = case == "grade_failed" or index.grade_documents_node.await_count > 1
                    return state
                index.grade_documents_node.side_effect = fail
            if case == "verifier_failed":
                index.verify_answer.side_effect = RuntimeError("offline")
            if case == "retry_grade_failed":
                index.verify_answer.return_value = verdict(missing=["missing"]), {}
            result = await index.run_rag("請解釋", files, AsyncMock())
        assert result["status"] == "unavailable" and not result["sources"]
        assert all(not b["source_ids"] for b in result["blocks"])
        assert "atomic" not in str(result["blocks"])
    asyncio.run(run())


def test_one_targeted_retrieval_and_one_repair_then_partial():
    async def run():
        with patches():
            index.verify_answer.return_value = verdict(missing=["missing"]), {}
            result = await index.run_rag("q", ["f1"], AsyncMock())
            assert index.retry_missing_concepts_node.await_count == 1
            assert index.generate_answer.await_count == 2
            assert index.verify_answer.await_count == 2
            assert index.generate_answer.await_args.kwargs["feedback"]["missing_topics"] == ["missing"]
        assert result["status"] == "partial"
    asyncio.run(run())


def test_missing_initial_evidence_can_be_recovered_once():
    async def run():
        with patches():
            plan = planner()
            plan["query_intent"]["required_concepts"] = ["atomicity"]
            index.plan_question.return_value = plan
            async def partial_grade(state, emit):
                state = await graded(state, emit)
                state["missing_concepts"] = ["atomicity"]
                return state
            index.grade_documents_node.side_effect = partial_grade
            index.build_context.side_effect = [[], [doc()]]
            result = await index.run_rag("q", ["f1"], AsyncMock())
            assert index.generate_answer.await_count == 1
        assert result["status"] == "complete"
    asyncio.run(run())


def test_stream_disconnect_cancels_worker():
    async def run():
        with patches():
            entered, cancelled = asyncio.Event(), asyncio.Event()
            async def slow(state, emit):
                await emit("start")
                entered.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()
            index.retrieve_documents_node.side_effect = slow
            stream = index.run_adaptive_rag_stream("q", ["f1"])
            await anext(stream)
            await entered.wait()
            await stream.aclose()
            assert cancelled.is_set()
    asyncio.run(run())


@pytest.mark.parametrize("value", [None, {}, planner() | {"decision": "bad"}, planner() | {"reason": ""}, planner()])
def test_planner_fallback_and_valid_plan(value):
    result = asyncio.run(routing.plan_question("q", generate_structured_json=AsyncMock(return_value=value), logger=index.logger))
    assert result["decision"] == "retrieve"
    assert result["query_intent"]["search_queries"]
