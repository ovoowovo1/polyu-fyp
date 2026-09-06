"""Evaluate the production RAG path against annotated evidence (no alternative pipeline).

PG_DSN must point to an isolated evaluation database/branch when --seed is used.
The caller supplies a teacher user ID; fixture documents are added to a new class.
"""
import argparse
import asyncio
import hashlib
import json
import statistics
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg2.extras import execute_values

from app.services.documents.document_service import _embed_chunks_for_storage
from app.services.pg.pg_db import _get_conn, close_pool
from app.services.pg.rls_context import set_current_rls_user, clear_current_rls_user
from app.services.rag.index import run_rag


def metrics(case, result, trace):
    expected = set(case['expected_source_ids'])
    cited = {s['chunk_id'] for s in result['sources']}
    candidates = {c['chunk_id'] for stage in trace['stages'] if stage['stage'] in ('retrieved', 'retry_retrieved') for c in stage['chunks']}
    return {
        'candidate_recall': len(expected & candidates) / len(expected) if expected else 1,
        'citation_precision': len(expected & cited) / len(cited) if cited else (0 if expected else 1),
        'citation_completeness': len(expected & cited) / len(expected) if expected else 1,
        'file_scope_correct': all(s['file_id'] in case['selected_file_ids'] for s in result['sources']),
        'source_ids_correct': cited <= expected,
        'latency_seconds': trace['latency_seconds'],
    }


async def seed(cases, user_id):
    sources = {s['chunk_id']: s for case in cases for s in case['sources']}
    chunks = [{'pageContent': s['content'], 'metadata': {'source': s['name'], 'pageNumber': s['page_start']}} for s in sources.values()]
    vectors = await _embed_chunks_for_storage(chunks)
    if len(vectors) != len(chunks):
        raise ValueError('Incomplete fixture embeddings')
    class_id = str(uuid4())
    with _get_conn() as conn, conn.cursor() as cur:
        # Refuse collisions: never replace existing document/chunk IDs.
        cur.execute("INSERT INTO classes(id,teacher_id,name) VALUES (%s,%s,'RAG evaluation fixtures')", (class_id, user_id))
        docs = {s['file_id']: s['name'] for s in sources.values()}
        for file_id, name in docs.items():
            file_hash = hashlib.sha256('\n'.join(s['content'] for s in sources.values() if s['file_id'] == file_id).encode()).hexdigest()
            cur.execute("INSERT INTO documents(id,class_id,name,hash,mimetype) VALUES (%s,%s,%s,%s,'text/plain')", (file_id, class_id, name, file_hash))
        rows = [(s['chunk_id'], s['file_id'], s['content'], s['page_start'], s['page_end'], s['chunk_index'], vectors[i])
                for i, s in enumerate(sources.values())]
        execute_values(cur, 'INSERT INTO chunks(id,document_id,text,page_start,page_end,chunk_index,embedding) VALUES %s',
            rows, template='(%s,%s,%s,%s,%s,%s,%s::vector)')
    # BM25 statistics must be refreshed outside a transaction after loading data.
    from app.config import get_settings
    import psycopg2
    connection = psycopg2.connect(get_settings().pg_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cur:
            cur.execute('VACUUM (ANALYZE) chunks')
    finally:
        connection.close()
    return class_id


async def main(args):
    cases = [c for c in json.loads(Path(args.cases).read_text(encoding='utf-8')) if c['scenario'] == 'normal']
    if args.limit:
        cases = cases[:args.limit]
    set_current_rls_user(args.user_id)
    reports = []
    output = Path(args.output)
    try:
        class_id = await seed(cases, args.user_id) if args.seed else None
        print(json.dumps({'fixture_class_id': class_id, 'case_count': len(cases)}), flush=True)
        for case in cases:
            trace = {}
            async def emit(*args, **kwargs):
                pass
            result = await run_rag(case['question'], case['selected_file_ids'], emit, trace=trace)
            report = {'id': case['id'], 'metrics': metrics(case, result, trace), 'result': result, 'trace': trace}
            reports.append(report)
            output.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'id': case['id'], 'status': result['status'], **report['metrics']}), flush=True)
        summary = {key: statistics.mean(r['metrics'][key] for r in reports) for key in ('candidate_recall', 'citation_precision', 'citation_completeness', 'latency_seconds')}
        summary['embedding_model'] = 'google/gemini-embedding-2'
        summary['embedding_dimensions'] = 3072
        summary['all_scopes_correct'] = all(r['metrics']['file_scope_correct'] for r in reports)
        summary['all_source_ids_correct'] = all(r['metrics']['source_ids_correct'] for r in reports)
        summary['targets_met'] = summary['candidate_recall'] >= .9 and summary['citation_precision'] >= .95 and summary['citation_completeness'] >= .9 and summary['all_scopes_correct'] and summary['all_source_ids_correct']
        output.with_suffix('.summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps(summary), flush=True)
        return 0 if summary['targets_met'] else 1
    finally:
        clear_current_rls_user()
        close_pool()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', default=str(Path(__file__).parent / 'fixtures/rag_cases.json'))
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--seed', action='store_true', help='Add fixtures only to an isolated database/branch')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--output', default='rag-evaluation.json')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
