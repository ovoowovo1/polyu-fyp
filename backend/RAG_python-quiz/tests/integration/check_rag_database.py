"""Exercise production SQL and reingestion against an isolated PostgreSQL database.

Run after the CI schema/migrations. Only newly created fixture rows are deleted.
No external models are called: the embedding boundary is deterministic.
"""
import asyncio
import hashlib
import io
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from psycopg2.extras import execute_values
from reportlab.pdfgen import canvas

from app.services.documents.reingest import reingest_pdf
from app.services.pg import pg_retrieval_service as retrieval
from app.services.pg.pg_db import _get_conn, close_pool
from app.services.pg.pg_retrieval_documents import replace_document_chunks
from app.services.pg.rls_context import set_current_rls_user, clear_current_rls_user
from app.services.core.exceptions import PermissionDeniedError, ValidationServiceError


async def main():
    teacher, outsider, class_id, private_class, file_id, foreign_file = [str(uuid4()) for _ in range(6)]
    first, second, foreign = [str(uuid4()) for _ in range(3)]
    vector = [1.0] + [0.0] * 3071
    pdf = io.BytesIO()
    document = canvas.Canvas(pdf)
    document.drawString(40, 800, 'Atomic transactions commit entirely or roll back entirely.')
    document.showPage()
    document.drawString(40, 800, 'Durability preserves committed changes after a restart.')
    document.save()
    content = pdf.getvalue()
    file_hash = hashlib.sha256(content).hexdigest()
    set_current_rls_user(teacher)
    try:
        with _get_conn() as conn, conn.cursor() as cur:
            for uid in (teacher, outsider):
                cur.execute("INSERT INTO users(id,email,password_hash,full_name,role) VALUES (%s,%s,'unused','RAG fixture','teacher')", (uid, uid+'@example.test'))
                cur.execute('INSERT INTO teachers(user_id) VALUES (%s)', (uid,))
            cur.execute("INSERT INTO classes(id,teacher_id,name) VALUES (%s,%s,'RAG fixture'),(%s,%s,'Private fixture')", (class_id, teacher, private_class, outsider))
            cur.execute("INSERT INTO documents(id,class_id,name,hash,mimetype) VALUES (%s,%s,'fixture.pdf',%s,'application/pdf'),(%s,%s,'private.pdf','private','application/pdf')", (file_id, class_id, file_hash, foreign_file, private_class))
            execute_values(cur, "INSERT INTO chunks(id,document_id,text,page_start,page_end,chunk_index,embedding) VALUES %s", [
                (first, file_id, 'Atomic transactions commit entirely.', 1, 1, 0, vector),
                (second, file_id, 'Durability preserves committed changes.', 2, 2, 1, vector),
                (foreign, foreign_file, 'Atomic transactions are private.', 1, 1, 0, vector)],
                template='(%s,%s,%s,%s,%s,%s,%s::vector)')
        lexical = retrieval.retrieve_context_by_keywords('Atomic', [file_id])
        assert lexical and all(row['fileId'] == file_id for row in lexical)
        assert retrieval.retrieve_context_by_keywords('Atomic', [foreign_file]) == []
        assert retrieval.retrieve_graph_context(vector, selected_file_ids=[foreign_file]) == []
        assert retrieval.retrieve_context_by_chunk_ids([{'chunkId': foreign, 'score': 1}], [foreign_file]) == []
        neighbors = retrieval.retrieve_adjacent_chunks([{'chunkId': first}], [file_id])
        assert {r['chunkId'] for r in neighbors} == {first, second}
        assert {r['page'] for r in neighbors} == {1, 2}
        assert retrieval.retrieve_adjacent_chunks([{'chunkId': first}], [foreign_file]) == []
        print('PASS scoped lexical, fuzzy, vector, cached and adjacent retrieval')

        def fail_insert(*args, **kwargs):
            raise RuntimeError('injected write failure')
        try:
            replace_document_chunks(get_conn=_get_conn, execute_values=fail_insert, file_id=file_id,
                user_id=teacher, expected_hash=file_hash, chunks=[{'text': 'replacement', 'embedding': vector}])
            raise AssertionError('Expected rollback')
        except RuntimeError as error:
            assert str(error) == 'injected write failure'
        assert {r['chunkId'] for r in retrieval.retrieve_adjacent_chunks([{'chunkId': first}], [file_id])} == {first, second}
        print('PASS real transaction rollback preserves original chunks')

        with patch('app.services.documents.document_service._embed_chunks_for_storage', AsyncMock(return_value=[vector, vector])), \
             patch('app.services.documents.reingest.redis_cache.invalidate_namespaces', AsyncMock()) as invalidate:
            for uid, data, error in ((outsider, content, PermissionDeniedError), (teacher, b'%PDF-wrong', ValidationServiceError)):
                try:
                    await reingest_pdf(file_id, uid, 'fixture.pdf', data, 'application/pdf')
                    raise AssertionError('Expected reingestion rejection')
                except error:
                    pass
            result = await reingest_pdf(file_id, teacher, 'fixture.pdf', content, 'application/pdf')
            assert result['chunksCount'] == 2 and result['fileId'] == file_id
            invalidate.assert_awaited_once()
        new_rows = retrieval.retrieve_graph_context(vector, selected_file_ids=[file_id])
        assert len(new_rows) == 2 and not {first, second}.intersection(r['chunkId'] for r in new_rows)
        assert any('roll back' in r['text'] for r in retrieval.retrieve_context_by_keywords('Atomic', [file_id]))
        assert retrieval.retrieve_context_by_chunk_ids([{'chunkId': first, 'score': 1}], [file_id]) == []
        print('PASS original hash, owner permission, PDF extraction, replacement, cache invalidation and new chunk retrieval')
    finally:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM documents WHERE id = ANY(%s::uuid[])', ([file_id, foreign_file],))
            cur.execute('DELETE FROM users WHERE id = ANY(%s::uuid[])', ([teacher, outsider],))
        clear_current_rls_user()
        close_pool()


if __name__ == '__main__':
    asyncio.run(main())
