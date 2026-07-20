# RAG Folder Refactor

## 目標

將 `backend/RAG_python-quiz/app/services/rag` 重整為以 `index.py` 為唯一頂層 RAG flow 入口，完整搬移至 orchestration、retrieval、generation、citation 與 shared 分層，並維持 API、SSE、retrieval 與 citation schema 不變。

## 計畫

- [x] 建立新 package folders 與 `__init__.py`，確認既有 dirty changes
- [x] 完成模組搬移並更新下層 import
- [x] 更新 router、agent、backend tests 的 import、mock target 與 patch path
- [x] 執行 package import/compile sanity check，清理舊路徑引用
- [x] 執行最後一次完整 backend pytest，確認 100% coverage

## 限制

- 完整搬移，不保留舊 flat module wrapper。
- `app.services.rag.index.run_adaptive_rag_stream` 是公開 flow 入口。
- 不改變 endpoint、SSE event、cache、retrieval 或 citation 行為。
- 保留工作樹中其他任務的既有變更。
