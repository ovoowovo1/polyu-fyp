import asyncio
import copy
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.services.rag.citation import service
from app.services.rag.citation.models import AnswerDraft, Verification


def doc(chunk_id="c1", text="A transaction is atomic.", **extra):
    return {"chunkId": chunk_id, "fileId": "f1", "source": "Notes.pdf", "page": 1,
            "page_end": 1, "chunk_index": 0, "text": text, **extra}


def draft(markdown="A transaction is atomic.", quote="A transaction is atomic.", source="c1"):
    return AnswerDraft.model_validate({"blocks": [{"id": "b1", "markdown": markdown,
        "kind": "factual", "evidence": [{"chunk_id": source, "quote": quote}]}], "limitations": []})


def verdict(supported=True, missing=None):
    return Verification.model_validate({"blocks": [{"id": "b1", "supported": supported, "reason": "checked"}],
                                         "missing_topics": missing or []})


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(unknown=True),
    lambda d: d["blocks"].append(copy.deepcopy(d["blocks"][0])),
    lambda d: d["blocks"][0].update(id=""),
    lambda d: d["blocks"][0].update(markdown=" "),
    lambda d: d["blocks"][0].update(kind="other"),
    lambda d: d["blocks"][0]["evidence"][0].update(quote=""),
    lambda d: d.update(limitations=[""]),
])
def test_draft_rejects_malformed_payload(mutate):
    value = draft().model_dump()
    mutate(value)
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate(value)


def test_verifier_schema_rejects_duplicate_ids_and_invalid_values():
    for change in ({"missing_topics": [""]}, {"blocks": [verdict().blocks[0].model_dump()] * 2},
                   {"blocks": [{"id": "b1", "supported": "yes", "reason": "checked"}]}):
        with pytest.raises(ValidationError):
            Verification.model_validate(verdict().model_dump() | change)


def test_structure_checks_missing_citations_quote_and_scope():
    assert service.check_structure(draft(), [doc()], ["f1"]) == {}
    assert service.check_structure(draft(quote="transaction is\n atomic"), [doc()], ["f1"]) == {}
    for answer, files in [(draft(source="foreign"), ["f1"]), (draft(), ["other"]), (draft(quote="false"), ["f1"])]:
        assert "b1" in service.check_structure(answer, [doc()], files)
    value = draft()
    value.blocks[0].evidence = []
    assert "b1" in service.check_structure(value, [doc()], ["f1"])


def test_model_block_ids_allow_hyphens_without_colliding_with_limitations():
    answer = draft().model_dump()
    answer["blocks"][0]["id"] = "limitation-0"
    answer["limitations"] = ["Missing cost data."]
    result = service.result_payload(AnswerDraft.model_validate(answer), [doc()], {}, [], "t", "q")
    assert len({b["id"] for b in result["blocks"]}) == 2
    assert result["blocks"][0]["source_ids"] == ["c1"]


def test_limitations_are_verified_and_unsupported_claims_are_removed():
    answer = draft()
    answer.limitations = ["Atomicity guarantees a 99% performance improvement."]
    response = verdict().model_dump()
    response['blocks'].append({'id': 'limitation:0', 'supported': False, 'reason': 'Unsupported factual claim'})
    async def run():
        with patch.object(service, 'generate_structured_json', AsyncMock(return_value=response)) as llm:
            _, errors = await service.verify_answer('q', answer, [doc()], ['f1'])
        assert 'limitation:0' in llm.call_args.args[0]
        result = service.result_payload(answer, [doc()], errors, [], 't', 'q')
        assert result['status'] == 'partial'
        assert '99%' not in str(result)
        assert result['sources'][0]['chunk_id'] == 'c1'
    asyncio.run(run())
    value = draft()
    value.blocks[0].kind = "structural"
    assert "b1" in service.check_structure(value, [doc()], ["f1"])


def test_generation_and_verifier_receive_same_full_evidence_and_images():
    documents = [doc(text="x" * 2200 + "Evidence after 800 characters.", image_data="data:image/png;base64,AA==")]
    answer = draft(quote="Evidence after 800 characters.")
    async def run():
        with patch.object(service, "generate_structured_json", AsyncMock(side_effect=[answer.model_dump(), verdict().model_dump()])) as llm:
            result = await service.generate_answer("請解釋", documents)
            checked, errors = await service.verify_answer("請解釋", result, documents, ["f1"])
        for call in llm.await_args_list:
            assert documents[0]["text"] in call.args[0]
            assert call.kwargs["image_inputs"][0]["chunk_id"] == "c1"
            assert "Traditional Chinese" in call.kwargs["system_prompt"]
        assert checked.blocks[0].supported and not errors
    asyncio.run(run())


def test_verifier_cannot_omit_blocks_and_can_reject_semantic_mismatch():
    async def run():
        with patch.object(service, "generate_structured_json", AsyncMock(return_value={"blocks": [], "missing_topics": []})):
            with pytest.raises(ValueError, match="exactly"):
                await service.verify_answer("q", draft(), [doc()], ["f1"])
        with patch.object(service, "generate_structured_json", AsyncMock(return_value=verdict(False).model_dump())):
            _, errors = await service.verify_answer("q", draft(), [doc()], ["f1"])
            assert errors == {"b1": "checked"}
    asyncio.run(run())


def test_result_preserves_order_multiple_sources_and_unreferenced_structure():
    answer = draft()
    answer.blocks.insert(0, type(answer.blocks[0])(id="heading", markdown="## Atomicity", kind="structural", evidence=[]))
    answer.blocks.append(answer.blocks[1].model_copy(update={"id": "b2"}))
    answer.blocks[1].evidence += [answer.blocks[1].evidence[0].model_copy(update={"chunk_id": "c2"})]
    result = service.result_payload(answer, [doc(), doc("c2", page=2), doc("unused")], {}, [], "trace", "q")
    assert result["status"] == "complete"
    assert [s["chunk_id"] for s in result["sources"]] == ["c1", "c2"]
    assert result["blocks"][0]["markdown"] == "## Atomicity"
    assert result["blocks"][1]["source_ids"] == ["c1", "c2"]
    assert result["sources"][1]["page_start"] == 2


@pytest.mark.parametrize("question", ["Explain", "請解釋"])
def test_unsupported_and_limitations_never_gain_arbitrary_citations(question):
    result = service.result_payload(draft(), [doc()], {"b1": "unsupported"}, [], "t", question)
    assert result["status"] == "unavailable" and not result["sources"]
    assert all(not b["source_ids"] for b in result["blocks"])
    result = service.result_payload(AnswerDraft(blocks=[], limitations=[]), [], {}, [], "t", question)
    assert result["limitations"] and result["status"] == "unavailable"
    result = service.result_payload(draft(), [doc()], {}, ["missing topic"], "t", question)
    assert result["status"] == "partial" and len(result["blocks"]) == 2
