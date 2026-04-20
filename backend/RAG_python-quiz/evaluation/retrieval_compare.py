# -*- coding: utf-8 -*-
"""
Comparison helpers for evaluation retrieval strategies.

This module deliberately reads evaluation credentials from `.env` or the shell
environment. Live provider keys must not be committed to source files.
"""

import asyncio
import os
import re
import sys
from typing import Any, Dict, List

from openai import OpenAI

# Keep the evaluation script runnable when executed directly from this folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import pg_service
from app.utils.dev_credentials import get_eval_embedding_credentials


class EvaluationEmbeddings:
    """Evaluation-only embedding client using env-driven credentials."""

    def __init__(self):
        credentials = get_eval_embedding_credentials()
        self.client = OpenAI(api_key=credentials.api_key, base_url=credentials.base_url)
        self.model_name = credentials.model

    def embed_query(self, text: str) -> List[float]:
        response = self.client.embeddings.create(
            model=self.model_name,
            input=text,
        )
        return response.data[0].embedding

    async def aembed_query(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.embed_query, text)


async def vector_only_search(
    query: str,
    selected_file_ids: List[str] = [],
    k: int = 20,
) -> List[Dict[str, Any]]:
    """Run vector-only retrieval against stored chunk embeddings."""

    embeddings = EvaluationEmbeddings()
    query_vector = await embeddings.aembed_query(query.strip())
    return await asyncio.to_thread(
        pg_service.retrieve_graph_context,
        query_vector,
        k,
        selected_file_ids,
    )


def sanitize_query_for_bm25(query: str) -> str:
    """Remove BM25 syntax characters that can break ParadeDB parsing."""

    special_chars = r'[`~!@#$%^&*()+=\[\]{}|\\:;"\'<>,?/]'
    cleaned = re.sub(special_chars, " ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "query"


async def fulltext_only_search(
    query: str,
    selected_file_ids: List[str] = [],
    k: int = 20,
) -> List[Dict[str, Any]]:
    """Run BM25-only keyword retrieval."""

    sanitized_query = sanitize_query_for_bm25(query)
    return await asyncio.to_thread(
        pg_service.retrieve_context_by_keywords,
        sanitized_query,
        selected_file_ids,
        k,
    )


def reciprocal_rank_fusion(
    results_list: List[List[Dict[str, Any]]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    """Fuse multiple ranked result lists with Reciprocal Rank Fusion."""

    rrf_scores: Dict[str, Dict[str, Any]] = {}

    for results in results_list:
        if not results:
            continue

        for rank, doc in enumerate(results, start=1):
            chunk_id = doc.get("chunkId")
            if not chunk_id:
                continue

            score = 1.0 / (k + rank)
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = {
                    "doc": doc,
                    "rrf_score": 0.0,
                    "sources": [],
                }
            rrf_scores[chunk_id]["rrf_score"] += score
            rrf_scores[chunk_id]["sources"].append({"rank": rank, "score": score})

    sorted_docs = sorted(
        rrf_scores.values(),
        key=lambda item: item["rrf_score"],
        reverse=True,
    )

    return [
        {**item["doc"], "rrf_score": round(item["rrf_score"], 4)}
        for item in sorted_docs
    ]


async def hybrid_search_rrf(
    query: str,
    selected_file_ids: List[str] = [],
    k: int = 20,
    rrf_k: int = 60,
) -> List[Dict[str, Any]]:
    """Run vector and keyword retrieval in parallel, then fuse with RRF."""

    vector_task = asyncio.create_task(vector_only_search(query, selected_file_ids, k * 2))
    fulltext_task = asyncio.create_task(fulltext_only_search(query, selected_file_ids, k * 2))
    vector_results, fulltext_results = await asyncio.gather(vector_task, fulltext_task)
    fused_results = reciprocal_rank_fusion([vector_results, fulltext_results], k=rrf_k)
    return fused_results[:k]


def format_contexts(results: List[Dict[str, Any]]) -> List[str]:
    """Extract plain context strings from retrieval results."""

    contexts = []
    for doc in results:
        text = doc.get("text") or doc.get("content") or ""
        contexts.append(text)
    return contexts


def get_context_string(results: List[Dict[str, Any]]) -> str:
    """Join retrieval results into a single text block."""

    return "\n\n---\n\n".join(format_contexts(results))
