"""Provider usage accounting. No prompts, credentials or response content are logged."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import math
from threading import Lock
from time import perf_counter
from uuid import uuid4
from urllib.parse import urlparse
from functools import wraps

from app.logger import get_logger

logger = get_logger(__name__)
_session = ContextVar("model_usage_session", default=None)
_operation = ContextVar("model_usage_operation", default=None)
FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_tokens",
          "cache_write_tokens", "reasoning_tokens", "cost_usd")


def value(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def number(raw):
    return raw if type(raw) in (int, float) and math.isfinite(raw) and raw >= 0 else None


def usage_values(response):
    usage = value(response, "usage")
    prompt = value(usage, "prompt_tokens_details") or value(usage, "input_tokens_details")
    completion = value(usage, "completion_tokens_details") or value(usage, "output_tokens_details")
    return {
        "input_tokens": number(value(usage, "prompt_tokens") if value(usage, "prompt_tokens") is not None else value(usage, "input_tokens")),
        "output_tokens": number(value(usage, "completion_tokens") if value(usage, "completion_tokens") is not None else value(usage, "output_tokens")),
        "total_tokens": number(value(usage, "total_tokens")),
        "cached_tokens": number(value(prompt, "cached_tokens")),
        "cache_write_tokens": number(value(prompt, "cache_write_tokens")),
        "reasoning_tokens": number(value(completion, "reasoning_tokens")),
        "cost_usd": number(value(usage, "cost")),
    }


@dataclass
class UsageSession:
    trace_id: str
    records: list = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)
    pending_calls: int = 0


def current_session_id():
    session = _session.get()
    return session.trace_id if session else None


def aggregate(records):
    result = {name: (sum(r[name] for r in records if r[name] is not None)
                     if any(r[name] is not None for r in records) else None) for name in FIELDS}
    result.update(model_calls=len(records),
                  usage_complete=all(all(r[k] is not None for k in (("input_tokens", "total_tokens") if r["kind"] == "embedding" else FIELDS[:3])) for r in records),
                  cost_complete=all(r["cost_usd"] is not None for r in records))
    return result


@contextmanager
def usage_scope(trace_id=None, *, label="ModelUsageSummary"):
    session = UsageSession(trace_id or str(uuid4()))
    token = _session.set(session)
    try:
        yield session
    finally:
        try:
            summary = {"trace_id": session.trace_id, **aggregate(session.records)}
            models = sorted({r["returned_model"] or r["requested_model"] for r in session.records})
            summary["models"] = {model: aggregate([r for r in session.records
                if (r["returned_model"] or r["requested_model"]) == model]) for model in models}
            summary["pending_calls"] = session.pending_calls
            if session.pending_calls:
                summary.update(usage_complete=False, cost_complete=False)
            logger.info("[%s] %s", label, json.dumps(summary, ensure_ascii=False))
        finally:
            _session.reset(token)


@contextmanager
def operation_scope(stage):
    if _session.get() is None:
        with usage_scope():
            with operation_scope(stage):
                yield
        return
    token = _operation.set({"id": str(uuid4()), "stage": stage, "attempt": 0})
    try:
        yield
    finally:
        _operation.reset(token)


def observed_call(call, *, stage, requested_model, kind="chat", **kwargs):
    """One record per transport attempt, before any application-level validation."""
    if _session.get() is None:
        with usage_scope():
            return observed_call(call, stage=stage, requested_model=requested_model, kind=kind, **kwargs)
    session = _session.get()
    operation = _operation.get()
    with session.lock:
        session.pending_calls += 1
        if operation:
            operation["attempt"] += 1
        attempt = operation["attempt"] if operation else 1
    record = {"trace_id": session.trace_id, "stage": stage, "kind": kind,
              "operation_id": operation["id"] if operation else str(uuid4()),
              "operation": operation["stage"] if operation else stage,
              "attempt": attempt, "requested_model": requested_model, "returned_model": None,
              "request_id": None, "outcome": "error", **dict.fromkeys(FIELDS)}
    started = perf_counter()
    try:
        response = call(**kwargs)
        payload = response
        if kind == "embedding":
            try:
                payload = response.json()
            except ValueError:
                payload = None
        record.update(usage_values(payload))
        returned_model, request_id = value(payload, "model"), value(payload, "id")
        record["returned_model"] = returned_model if isinstance(returned_model, str) else None
        record["request_id"] = request_id if isinstance(request_id, str) else None
        record["outcome"] = "error" if value(payload, "error") or (kind == "embedding" and response.status_code >= 400) else "response_received"
        return response
    except Exception as error:
        record["error_type"] = type(error).__name__
        raise
    finally:
        record["latency_ms"] = round((perf_counter() - started) * 1000, 2)
        with session.lock:
            session.records.append(record)
            session.pending_calls -= 1
        logger.info("[ModelUsage] %s", json.dumps(record, ensure_ascii=False))


def chat_completion(client, *, stage, **kwargs):
    # Session affinity is a routing hint, not an assertion of a cache hit.
    if urlparse(str(getattr(client, "base_url", ""))).hostname == "openrouter.ai" and current_session_id():
        kwargs["extra_body"] = {**kwargs.get("extra_body", {}), "session_id": current_session_id()}
    return observed_call(client.chat.completions.create, stage=stage,
                         requested_model=kwargs.get("model", "unknown"), **kwargs)


def model_workflow(label):
    """Share a trace across an entire quiz/exam/document workflow and its worker threads."""
    def decorate(func):
        @wraps(func)
        async def wrapped(*args, **kwargs):
            if _session.get() is not None:
                return await func(*args, **kwargs)
            with usage_scope(label=label):
                return await func(*args, **kwargs)
        return wrapped
    return decorate
