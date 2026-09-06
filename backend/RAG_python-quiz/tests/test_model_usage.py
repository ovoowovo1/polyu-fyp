import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from app.utils import model_usage as usage
from tests.support import FakeResponse


def response(**updates):
    data = dict(id="request-1", model="returned-model", usage={
        "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 10},
        "completion_tokens_details": {"reasoning_tokens": 5}, "cost": 0.002})
    data.update(updates)
    return NS(**data)


def test_usage_fields_do_not_double_count_and_unknowns_are_null():
    actual = usage.usage_values(response())
    assert actual == dict(input_tokens=100, output_tokens=20, total_tokens=120,
                          cached_tokens=80, cache_write_tokens=10, reasoning_tokens=5, cost_usd=.002)
    assert set(usage.usage_values(None).values()) == {None}
    other = usage.usage_values({"usage": {"input_tokens": 0, "output_tokens": 2,
        "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 1}}})
    assert other["input_tokens"] == 0 and other["cached_tokens"] == 0 and other["total_tokens"] is None
    for invalid in (True, "12", -1, float("inf"), float("nan")):
        assert usage.number(invalid) is None


def test_attempts_keep_error_and_returned_usage_without_content(caplog):
    call = Mock(side_effect=[TimeoutError("SECRET"), response()])
    with usage.usage_scope("trace") as session, usage.operation_scope("generate"):
        with pytest.raises(TimeoutError):
            usage.observed_call(call, stage="generate", requested_model="requested")
        usage.observed_call(call, stage="generate", requested_model="requested")
    first, second = session.records
    assert [first["attempt"], second["attempt"]] == [1, 2]
    assert first["operation_id"] == second["operation_id"]
    assert first["total_tokens"] is None and first["outcome"] == "error"
    assert second["requested_model"] == "requested" and second["returned_model"] == "returned-model"
    assert second["request_id"] == "request-1" and second["total_tokens"] == 120
    summary = usage.aggregate(session.records)
    assert summary["model_calls"] == 2 and summary["input_tokens"] == 100
    assert not summary["usage_complete"] and not summary["cost_complete"]
    assert "SECRET" not in caplog.text
    assert usage.current_session_id() is None


def test_embedding_usage_and_invalid_http_json_are_recorded():
    with usage.usage_scope() as session:
        for reply in [FakeResponse(payload={"usage": {"prompt_tokens": 30, "total_tokens": 30}}),
                      FakeResponse(status_code=503, json_error=ValueError()),
                      FakeResponse(payload={"error": {"message": "failure"}})]:
            assert usage.observed_call(lambda: reply, stage="embedding", requested_model="gemini", kind="embedding") is reply
    assert session.records[0]["output_tokens"] is None
    assert usage.aggregate(session.records[:1])["usage_complete"]
    assert session.records[1]["outcome"] == session.records[2]["outcome"] == "error"


def test_standalone_call_operation_and_unknown_provider():
    with patch.object(usage.logger, "info") as log:
        usage.observed_call(lambda: response(model=123, id=123), stage="standalone", requested_model="m")
        with usage.operation_scope("standalone-operation"):
            usage.observed_call(lambda: {}, stage="op", requested_model="m")
    records = [json.loads(c.args[-1]) for c in log.call_args_list if c.args[0].startswith("[ModelUsage]")]
    assert records[0]["returned_model"] is None and records[0]["request_id"] is None
    assert records[0]["trace_id"] != records[1]["trace_id"]


def test_routing_hint_uses_same_session_without_claiming_cache_hit():
    create = Mock(return_value=response())
    client = NS(base_url="https://openrouter.ai/api/v1", chat=NS(completions=NS(create=create)))
    with usage.usage_scope("shared-trace"):
        usage.chat_completion(client, stage="answer", model="model", extra_body={"other": True})
        usage.chat_completion(client, stage="verify", model="model")
    assert create.call_args_list[0].kwargs["extra_body"] == {"other": True, "session_id": "shared-trace"}
    assert create.call_args_list[1].kwargs["extra_body"] == {"session_id": "shared-trace"}
    client.base_url = "https://openrouter.ai.example.test/v1"
    usage.chat_completion(client, stage="answer", model="model")
    assert "extra_body" not in create.call_args.kwargs


def test_parallel_scopes_are_isolated_and_threads_share_the_parent():
    async def run(name):
        with usage.usage_scope(name) as session:
            async def one():
                with usage.operation_scope("grade"):
                    await asyncio.to_thread(usage.observed_call, lambda: response(), stage="grade", requested_model="m")
            await asyncio.gather(one(), one())
        return session
    async def both():
        return await asyncio.gather(run("a"), run("b"))
    a, b = asyncio.run(both())
    for session in (a, b):
        assert len(session.records) == 2
        assert all(r["trace_id"] == session.trace_id and r["attempt"] == 1 for r in session.records)
        assert len({r["operation_id"] for r in session.records}) == 2


def test_workflow_wrapper_and_pending_call_summary():
    @usage.model_workflow("QuizUsage")
    async def work():
        usage.observed_call(lambda: response(), stage="quiz", requested_model="m")
        return usage.current_session_id()
    async def run():
        standalone = await work()
        with usage.usage_scope("outer") as session:
            assert await work() == "outer"
            session.pending_calls = 1
        return standalone
    with patch.object(usage.logger, "info") as log:
        assert asyncio.run(run()) != "outer"
    summary = json.loads(log.call_args.args[-1])
    assert summary["pending_calls"] == 1 and not summary["usage_complete"]
    assert usage.current_session_id() is None


def test_provider_http_is_blocked_without_a_paid_request():
    import requests
    import httpx
    with pytest.raises(AssertionError, match="disabled"):
        requests.post("https://openrouter.ai/api/v1/chat/completions", json={})
    with pytest.raises(AssertionError, match="disabled"):
        httpx.Client().post("https://openrouter.ai/api/v1/chat/completions", json={})
