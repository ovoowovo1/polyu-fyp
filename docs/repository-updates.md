# Repository Updates

This document records ongoing repository updates that were added after the FYP final report snapshot.

These notes describe the current maintained implementation state of the codebase. They are not a restatement of the formal FYP progress record, assessed submission scope, or final-report milestone status.

## Post-FYP Implementation Updates

### Adaptive RAG and Retrieval Update

Repository update summary:

- Adaptive RAG was added to the `/query-stream` grounded Q&A flow.
- The exam retriever now uses a shared adaptive retrieval pipeline.
- Chunk relevance grading in adaptive retrieval was parallelized to reduce end-to-end generation time.
- Fulltext retrieval now returns the real document `source` name instead of falling back to `Unknown source` in the normal path.

Implementation scope note:

- This update reflects the repository's current engineering state after the FYP project snapshot shown in Figure 4.1 of the root README.
- It should not be interpreted as part of the official FYP progress record or formal assessed deliverables.
