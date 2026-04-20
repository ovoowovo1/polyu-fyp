# -*- coding: utf-8 -*-
"""
RAGAS configuration helpers for evaluation scripts.

These utilities intentionally load credentials from `.env` or the shell
environment. Live provider keys must not be committed to source files.
"""

import os
import sys
from typing import List

from openai import OpenAI
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

# Keep the evaluation script runnable when executed directly from this folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.dev_credentials import get_eval_embedding_credentials, get_eval_llm_credentials


class DirectOpenAIEmbeddings(Embeddings):
    """OpenAI-compatible embeddings wrapper without LangChain tokenization."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        valid_texts = [text if text and text.strip() else "empty" for text in texts]
        response = self.client.embeddings.create(model=self.model, input=valid_texts)
        sorted_data = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in sorted_data]

    def embed_query(self, text: str) -> List[float]:
        query = text if text and text.strip() else "empty"
        response = self.client.embeddings.create(model=self.model, input=query)
        return response.data[0].embedding


def get_ragas_llm():
    """Build the LLM used by RAGAS evaluation."""

    credentials = get_eval_llm_credentials()

    print(f"[RAGAS CONFIG] Using base_url: {credentials.base_url}")
    print(f"[RAGAS CONFIG] Using model: {credentials.model}")
    print("[RAGAS CONFIG] Using api_key: [configured]")

    llm = ChatOpenAI(
        base_url=credentials.base_url,
        api_key=credentials.api_key,
        model=credentials.model,
        temperature=0.0,
        timeout=120,
        max_retries=3,
    )
    return LangchainLLMWrapper(llm)


def get_ragas_embeddings():
    """Build the embeddings model used by RAGAS evaluation."""

    credentials = get_eval_embedding_credentials()
    embeddings = DirectOpenAIEmbeddings(
        api_key=credentials.api_key,
        base_url=credentials.base_url,
        model=credentials.model,
    )
    return LangchainEmbeddingsWrapper(embeddings)


def configure_ragas():
    """Return the configured RAGAS LLM and embedding wrappers."""

    return get_ragas_llm(), get_ragas_embeddings()
