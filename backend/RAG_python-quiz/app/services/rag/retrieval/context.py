"""Coverage-first selection; keep original chunks and identifiers intact."""
import asyncio
import json
import math

from app.services.pg.pg_retrieval_service import retrieve_adjacent_chunks

MAX_CORE_CHUNKS = 16
MAX_CONTEXT_CHUNKS = 24
MAX_CONTEXT_TOKENS = 16000


def select_core(documents: list[dict], required: list[str]) -> list[dict]:
    remaining = list(documents)
    uncovered = set(required)
    selected = []
    while remaining and len(selected) < MAX_CORE_CHUNKS:
        best = max(remaining, key=lambda d: (len(uncovered.intersection(d.get("covered_concepts", []))),
                   d.get("relevance_score", 0), d.get("rrf_score", 0)))
        selected.append(best)
        remaining.remove(best)
        uncovered.difference_update(best.get("covered_concepts", []))
    return selected


async def build_context(documents: list[dict], selected_file_ids: list[str], required: list[str]) -> list[dict]:
    core = select_core([d for d in documents if d.get("fileId") in selected_file_ids], required)
    adjacent = await asyncio.to_thread(retrieve_adjacent_chunks, core, selected_file_ids) if core else []
    result, seen, tokens, images = [], set(), 0, 0
    for doc in core + adjacent:
        if doc["chunkId"] in seen or doc["fileId"] not in selected_file_ids:
            continue
        text = json.dumps({k: v for k, v in doc.items() if k != "image_data"}, ensure_ascii=False)
        # Conservative multilingual estimate; no network-dependent tokenizer at import time.
        count = math.ceil(sum(1 / 3 if ord(c) < 128 else 2 for c in text)) + 64
        is_image = bool(doc.get("image_data"))
        count += 1500 if is_image else 0
        if len(result) >= MAX_CONTEXT_CHUNKS or tokens + count > MAX_CONTEXT_TOKENS or (is_image and images >= 6):
            continue
        result.append(doc)
        seen.add(doc["chunkId"])
        tokens += count
        images += int(is_image)
    return result
