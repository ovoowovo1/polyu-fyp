"""Live PDF import/reimport regression. Run only against an isolated database branch."""
import argparse
import asyncio
import io
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from app.services.documents.document_service import ingest_document
from app.services.documents.reingest import reingest_pdf
from app.services.pg.pg_db import _get_conn, close_pool
from app.services.pg.rls_context import set_current_rls_user, clear_current_rls_user
from app.services.pg import pg_retrieval_service as retrieval
from app.services.rag.index import run_rag


def fixture_pdf():
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    for page in range(1, 8):
        pdf.drawString(40, 800, f'Page {page}: Atomicity means a transaction commits entirely or rolls back entirely.')
        picture = Image.new('RGB', (320, 160), 'white')
        draw = ImageDraw.Draw(picture)
        draw.rectangle((20, 20, 300, 140), outline=(page * 30, 40, 120), width=5)
        draw.text((40, 70), f'TRANSACTION {page}: ALL OR NOTHING', fill='black')
        pdf.drawImage(ImageReader(picture), 40, 570, width=320, height=160)
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


async def main(args):
    class_id, file_id = str(uuid4()), None
    set_current_rls_user(args.user_id)
    try:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO classes(id,teacher_id,name) VALUES (%s,%s,'Single embedding live regression')", (class_id, args.user_id))
        content = args.pdf.read_bytes() if args.pdf else fixture_pdf()
        filename = args.pdf.name if args.pdf else 'single-embedding-text-and-images.pdf'
        first = await ingest_document(filename=filename, content=content, size=len(content), mimetype='application/pdf', class_id=class_id, user_id=args.user_id)
        file_id = first['fileId']
        def snapshot():
            with _get_conn() as conn, conn.cursor() as cur:
                cur.execute('SELECT c.id,c.page_start,c.chunk_index,vector_dims(c.embedding),m.data FROM chunks c LEFT JOIN chunk_media m ON m.chunk_id=c.id WHERE c.document_id=%s ORDER BY c.chunk_index', (file_id,))
                return [tuple(row.values()) for row in cur.fetchall()]
        before = snapshot()
        assert before and all(row[3] == 3072 for row in before)
        assert sum(row[4] is not None for row in before) >= (1 if args.pdf else 7)
        second = await reingest_pdf(file_id, args.user_id, filename, content, 'application/pdf')
        after = snapshot()
        assert second['fileId'] == file_id and len(after) == len(before)
        assert not {str(r[0]) for r in before} & {str(r[0]) for r in after}
        assert [(r[1], r[2], r[3], bytes(r[4]) if r[4] else None) for r in before] == [(r[1], r[2], r[3], bytes(r[4]) if r[4] else None) for r in after]
        hydrated = retrieval.retrieve_context_by_chunk_ids([{'chunkId': str(row[0]), 'score': 1} for row in after], [file_id])
        assert len(hydrated) == len(after)
        for source, row in zip(hydrated, after):
            assert source['page'] == row[1] and source['chunkId'] == str(row[0])
            if row[4]:
                assert source['image_data'].startswith('data:image/')
        async def emit(*args, **kwargs):
            pass
        result = await run_rag('What does atomicity mean?', [file_id], emit)
        assert result['status'] in ('complete', 'partial') and result['sources']
        assert all(source['file_id'] == file_id and source['chunk_id'] in {str(row[0]) for row in after} for source in result['sources'])
        print(json.dumps({'model': 'google/gemini-embedding-2', 'dimensions': 3072, 'chunks': len(after), 'images': sum(row[4] is not None for row in after), 'reingest': 'passed', 'source_mapping': 'passed', 'rag_status': result['status']}), flush=True)
    finally:
        with _get_conn() as conn, conn.cursor() as cur:
            if file_id:
                cur.execute('DELETE FROM documents WHERE id=%s', (file_id,))
            cur.execute('DELETE FROM classes WHERE id=%s', (class_id,))
        clear_current_rls_user()
        close_pool()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--pdf', type=Path)
    asyncio.run(main(parser.parse_args()))
