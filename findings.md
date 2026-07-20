# Findings

- 原本 `app/services/rag` 有 25 個 flat modules，已按 orchestration、retrieval、generation、citation、shared 完整搬移。
- `adaptive_rag_service.py` 原本承擔頂層 stream flow，現在對應為 `index.py`。
- `app.services.rag.__init__` 只 re-export `run_adaptive_rag_stream`。
- lower-level RAG modules 沒有反向 import `index.py`，避免 circular import。
- router、retriever agent 與 backend tests 的 import、mock target 已更新。
- `query_stream.py` 直接 import `app.services.rag.index.run_adaptive_rag_stream`。
- website 與 Expo 仍呼叫 `/api/query-stream`，並使用既有 SSE event、`answer_with_citations` 與 `raw_sources` 欄位；此次沒有修改 frontend。
- 已保留既有 full-text sanitizer、PostgreSQL pool、Redis async 與 retrieval cache 行為。
