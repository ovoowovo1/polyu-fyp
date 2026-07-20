# Progress

## 2026-07-20

- 已建立 RAG 分層 package 骨架與頂層 `index.py`。
- 因 `.git/index.lock` 權限錯誤，改用檔案搬移完成完整搬移，未使用 destructive git 操作。
- 已更新 production import、router、retriever agent、backend tests 的 import 與 mock path。
- 已通過 package compile/import sanity check。
- 已檢查 website 與 Expo 的 query-stream/citation 呼叫鏈；endpoint、SSE event 與 citation payload 未改變。
- 完成最後一次完整 backend pytest：473 tests passed，coverage 100%。
