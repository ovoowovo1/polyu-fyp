# -*- coding: utf-8 -*-
"""
RAGAS 評估框架 - evaluation 模組

此模組提供 RAG 檢索策略的比較評估功能。
"""

from .retrieval_compare import (
    vector_only_search,
    fulltext_only_search,
    hybrid_search_rrf,
    format_contexts,
    get_context_string,
)

from .ragas_config import (
    get_ragas_llm,
    get_ragas_embeddings,
    configure_ragas,
)

__all__ = [
    "vector_only_search",
    "fulltext_only_search", 
    "hybrid_search_rrf",
    "format_contexts",
    "get_context_string",
    "get_ragas_llm",
    "get_ragas_embeddings",
    "configure_ragas",
]
