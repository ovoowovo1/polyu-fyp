import asyncio
from unittest.mock import AsyncMock, Mock, patch

import psycopg2
import pytest

from app.services.core.exceptions import PermissionDeniedError, ValidationServiceError
from app.services.pg import pg_retrieval_service as pg
from app.services.pg import pg_retrieval_keywords as keywords
from app.services.pg import pg_retrieval_documents as writes
from app.services.documents import reingest, ingestion_steps
from app.services.documents.chunking import DocumentSplitter
from app.services.rag.retrieval import context, grading
from tests.support import FakeConnection, FakeCursor
from tests.test_citation_evidence_service import doc


def row(chunk_id="c1"):
    return {"chunkid": chunk_id, "fileid": "f1", "source": "Notes.pdf", "text": "atomic",
            "page_start": 1, "page_end": 2, "chunk_index": 3, "score": .5}


@pytest.mark.parametrize("backend", ["lakebase_text", "postgres"])
def test_keyword_channels_have_separate_ranks_and_scoped_sql(backend):
    cur = FakeCursor(fetchall_results=[[row()], [row("c2"), row()]])
    conn = FakeConnection(cur)
    result = keywords.retrieve_context_by_keywords(get_conn=lambda: conn, backend=backend,
        keywords='text:(sql) OR admin', selected_file_ids=["f1"], k=3)
    assert result[0]["lexical_rank"] == 1 and result[0]["fuzzy_rank"] == 2
    assert result[1]["fuzzy_rank"] == 1
    for sql, params in cur.executed[-2:]:
        assert 'AND c.document_id = ANY(%s::uuid[])' in sql
        assert params == ['text:(sql) OR admin'] * 2 + [["f1"], 3]
    assert 'word_similarity' in cur.executed[-1][0]
    lexical = cur.executed[-2][0]
    assert 'c.tsv @@ query.ts_query' in lexical
    assert ('ORDER BY score ASC' in lexical) == (backend == 'lakebase_text')
    assert result[0]["page_end"] == 2 and result[0]["chunk_index"] == 3


def test_lakebase_failure_rolls_back_and_retries_native_fts():
    cur = FakeCursor(fetchall_results=[[row()], []])
    failed = Mock()
    failed.__enter__ = Mock(side_effect=psycopg2.ProgrammingError("extension unavailable"))
    failed.__exit__ = Mock(return_value=False)
    connection = Mock(side_effect=[failed, FakeConnection(cur), FakeConnection(cur)])
    result = keywords.retrieve_context_by_keywords(get_conn=connection, backend="lakebase_text",
        keywords="atomic", selected_file_ids=["f1"], k=3)
    assert result[0]["chunkId"] == "c1"
    assert 'ts_rank_cd' in cur.executed[0][0]
    with pytest.raises(psycopg2.Error):
        keywords.retrieve_context_by_keywords(get_conn=lambda: failed, backend="postgres",
            keywords="atomic", selected_file_ids=["f1"], k=3)


def test_all_retrieval_paths_reject_empty_scope_and_adjacent_is_scoped():
    unopened = Mock(side_effect=AssertionError("must not query"))
    assert keywords.retrieve_context_by_keywords(get_conn=unopened, backend="postgres", keywords="q", selected_file_ids=[], k=3) == []
    assert keywords.retrieve_context_by_keywords(get_conn=unopened, backend="postgres", keywords=" ", selected_file_ids=["f1"], k=3) == []
    with patch.object(pg, "_get_conn", unopened):
        assert pg.retrieve_graph_context([1.0], selected_file_ids=[]) == []
        assert pg.retrieve_adjacent_chunks([], ["f1"]) == []
    cur = FakeCursor(fetchall_results=[[row()]])
    with patch.object(pg, "_get_conn", return_value=FakeConnection(cur)):
        result = pg.retrieve_adjacent_chunks([doc()], ["f1"])
    assert result[0]["chunkId"] == "c1"
    assert cur.executed[0][1] == (["c1"], ["f1"], ["f1"])
    assert 'anchor.chunk_index - 1' in cur.executed[0][0]


def test_core_coverage_neighbors_and_token_image_limits():
    docs = [doc(f"c{i}", covered_concepts=["late"] if i == 19 else ["early"], relevance_score=1-i/100) for i in range(20)]
    assert context.select_core(docs, ["early", "late"])[1]["chunkId"] == "c19"
    async def run():
        with patch.object(context, "retrieve_adjacent_chunks", return_value=[doc(), doc(fileId="outside")] + [doc(f"n{i}") for i in range(20)]):
            selected = await context.build_context(docs, ["f1"], ["early", "late"])
        assert len(selected) == 24 and len({d["chunkId"] for d in selected}) == 24
        assert all(d["fileId"] == "f1" for d in selected)
        with patch.object(context, "retrieve_adjacent_chunks", return_value=[]):
            images = [doc(f"im{i}", image_data="data:image/png;base64,AA==") for i in range(8)]
            selected = await context.build_context([doc(text="字" * 16000)] + images, ["f1"], [])
            assert len(selected) == 6
            assert await context.build_context([], ["f1"], []) == []
    asyncio.run(run())


def test_splitter_keeps_short_chinese_code_tables_and_line_overlap():
    splitter = DocumentSplitter(chunk_size=100, chunk_overlap=25)
    assert splitter.split_text("標題") == ["標題"]
    table = '| A | B |\n|---|---|\n' + '\n'.join(f'| {i} | value {i} |' for i in range(20))
    chunks = splitter.split_text(table)
    assert len(chunks) > 1 and all(c.startswith('| A | B |\n|---|---|') for c in chunks)
    code = '```python\n' + '\n'.join(f'print({i})' for i in range(30)) + '\n```'
    chunks = splitter.split_text(code)
    assert len(chunks) > 1 and all(c.startswith('```python\n') and c.endswith('\n```') for c in chunks)
    assert all(f'print({i})' in '\n'.join(chunks) for i in range(30))
    assert splitter.split_text('甲。乙！丙？丁；' * 30)
    assert splitter.split_lines([]) == []


@pytest.mark.parametrize("fail", [None, "permission", "hash", "insert", "empty"])
def test_reingest_transaction_rechecks_permissions_hash_and_rolls_back(fail):
    cur = FakeCursor(fetchone_results=[None if fail == "permission" else {"hash": "wrong" if fail == "hash" else "hash"}])
    conn = FakeConnection(cur)
    insert = Mock(side_effect=RuntimeError("insert failed") if fail == "insert" else None)
    args = dict(get_conn=lambda: conn, execute_values=insert, file_id="f1", user_id="teacher",
                expected_hash="hash", chunks=[] if fail == "empty" else [{"text": "new", "embedding": [1.0]}])
    if fail:
        with pytest.raises((PermissionDeniedError, ValidationServiceError, RuntimeError)):
            writes.replace_document_chunks(**args)
        assert not conn.committed
        assert conn.rolled_back == (fail != "empty")
    else:
        assert writes.replace_document_chunks(**args)["chunksCount"] == 1
        assert conn.committed and not conn.rolled_back
        assert 'FOR UPDATE OF d, c' in cur.executed[0][0]
        assert cur.executed[1][1] == ("f1",)
        assert insert.call_args.args[2][0][0] == "f1"


def test_reingest_source_ownership_read():
    cur = FakeCursor(fetchone_results=[{"hash": "h"}, None])
    args = dict(get_conn=lambda: FakeConnection(cur), file_id="f1", user_id="teacher")
    assert writes.get_reingest_document(**args) == {"hash": "h"}
    with pytest.raises(PermissionDeniedError):
        writes.get_reingest_document(**args)


@pytest.mark.parametrize("failure", [None, "mime", "hash", "embedding", "database"])
def test_reingest_prepares_before_write_and_invalidates_only_after_success(failure):
    content = b'%PDF-original'
    async def run():
        with patch.object(reingest, "get_reingest_document", return_value={"hash": "wrong" if failure == "hash" else ingestion_steps.content_hash(content), "name": "Notes.pdf"}), \
             patch.object(reingest.documents, "extract_pdf_content_by_page", AsyncMock(return_value=["短文字"])), \
             patch.object(reingest.documents, "_embed_chunks_for_storage", AsyncMock(return_value=[] if failure == "embedding" else [[1.0]])), \
             patch.object(reingest, "replace_document_chunks", Mock(side_effect=RuntimeError("db") if failure == "database" else None, return_value={"fileId": "f1", "status": "success"})) as replace, \
             patch.object(reingest, "publish_progress", AsyncMock()) as publish, \
             patch.object(reingest.redis_cache, "invalidate_namespaces", AsyncMock()) as invalidate:
            if failure:
                with pytest.raises((ValidationServiceError, RuntimeError)):
                    await reingest.reingest_pdf("f1", "teacher", "bad.txt" if failure == "mime" else "original.pdf", content, "text/plain")
                invalidate.assert_not_awaited()
                if failure != "database":
                    replace.assert_not_called()
            else:
                result = await reingest.reingest_pdf("f1", "teacher", "original.pdf", content, "application/pdf", "client")
                assert result["fileId"] == "f1"
                assert replace.call_args.kwargs["chunks"][0]["text"] == "短文字"
                invalidate.assert_awaited_once_with("files:list", "files:detail:f1", "chunks:source-details", "rag:retrieval")
                assert publish.await_args.args[1]["type"] == "finished"
    asyncio.run(run())


def test_grading_40_candidates_runs_batches_of_8_with_concurrency_2():
    async def run():
        active = maximum = 0
        batches = []
        async def llm(prompt, schema, **kwargs):
            nonlocal active, maximum
            import re
            ids = re.findall(r'\[Chunk (c\d+)\]', prompt)
            batches.append(ids)
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return {"grades": [{"chunk_id": value, "relevance_score": .8, "covered_concepts": [], "reason": "supported"} for value in ids]}
        state = {"question": "q", "candidate_documents": [doc(f"c{i}") for i in range(40)],
                 "query_intent": {"required_concepts": [], "intent_type": "single"}}
        result = await grading.grade_documents_node(state, AsyncMock(), log_prefix="test", generate_structured_json_func=llm)
        assert [len(b) for b in batches] == [8] * 5
        assert maximum == 2 and len(result["filtered_documents"]) == 40
    asyncio.run(run())


def test_source_metadata_multimodal_and_splitter_long_line():
    from app.services.ai.llm.multimodal import build_multimodal_content
    content = build_multimodal_content('text', [{"chunk_id": "c1", "image_data": "data:image/png;base64,AA=="}])
    assert content[1]["text"] == "Image for chunk_id: c1"
    assert DocumentSplitter(50, 40).split_lines(['small', 'other', 'x' * 80])[-1] == 'x' * 80
    assert asyncio.run(grading.run_document_grader('prompt', {}, generate_structured_json_func=AsyncMock(return_value={}))) == {}


def test_vector_cache_hydration_keeps_selected_file_scope():
    from app.services.rag.retrieval import vector
    from tests.test_vector_query_service import patched_vector_dependencies, SuccessfulQueryModel
    async def cached(*args, rehydrate, **kwargs):
        return await rehydrate([{'chunkId': 'c1', 'score': .1}])
    async def run():
        with patched_vector_dependencies(SuccessfulQueryModel('model', [1.0])), \
             patch.object(vector.rag_cache, 'get_or_set_retrieval_rows', side_effect=cached), \
             patch.object(vector.pg_service, 'retrieve_context_by_chunk_ids', return_value=[doc()]) as hydrate:
            result, mode = await vector.retrieve_vector_context('q', ['f1'])
        assert result == [doc()] and mode == 'single'
        hydrate.assert_called_once_with([{'chunkId': 'c1', 'score': .1}], ['f1'])
    asyncio.run(run())


def test_keyword_public_wrapper_defaults_and_validates_settings():
    from tests.support import make_settings
    with patch.object(pg, 'get_settings', return_value=make_settings()), patch.object(keywords, 'retrieve_context_by_keywords', return_value=[doc()]) as search:
        assert pg.retrieve_context_by_keywords('q', ['f1']) == [doc()]
        assert search.call_args.kwargs['backend'] == 'lakebase_text'


def test_reingest_route_permission_failure_and_success():
    from app.routers import files_pg
    from tests.support import build_authed_client
    _, client = build_authed_client(files_pg.router, files_pg.get_current_user, {'user_id': 'teacher'})
    with patch.object(files_pg, 'reingest_pdf', AsyncMock(return_value={'status': 'success', 'fileId': 'f1'})) as service:
        response = client.post('/api/files/f1/reingest?clientId=client', files={'file': ('notes.pdf', b'%PDF-file', 'application/pdf')})
        assert response.status_code == 200
        service.assert_awaited_once_with('f1', 'teacher', 'notes.pdf', b'%PDF-file', 'application/pdf', 'client')
    with patch.object(files_pg, 'reingest_pdf', AsyncMock(side_effect=PermissionDeniedError())):
        assert client.post('/api/files/f1/reingest', files={'file': ('a.pdf', b'x')}).status_code == 403
