# AGENTS.md

This file contains repository-specific instructions for AI agents working in this project.

## Working Agreement

- Treat this file as the canonical AI-only instruction source for repository workflow rules.
- Do not overwrite, revert, or otherwise disturb unrelated uncommitted changes already present in the worktree.
- Do not claim a task is complete if required verification was not run or if required verification failed.

## Required Verification

### Backend Changes

If you modify backend code or backend tests under `backend/RAG_python-quiz`, you must run the backend test suite from `backend/RAG_python-quiz` with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Backend work is only complete if:

- The `pytest` run passes.
- Coverage still satisfies the existing `--cov-fail-under=100` rule defined in `backend/RAG_python-quiz/pytest.ini`.

If backend tests pass but coverage drops below 100%, you must add or update tests before considering the task complete.

### Frontend Changes

If you modify frontend files under `fontend/vite-project`, you must run the relevant frontend tests from `fontend/vite-project`:

```powershell
node --test
```

Frontend work is only complete if the relevant frontend tests pass. Full frontend coverage is not required yet.

### Full-Stack Changes

If you modify both backend and frontend files, you must run both verification command sets. Backend changes must still satisfy 100% coverage.

## Final Response Requirements

Your final response must:

- List the exact verification commands you ran.
- State clearly whether each required verification step passed or failed.
- Treat the task as blocked or incomplete if a required test command could not be run.

## Blocked Environment Handling

If verification cannot be completed because of missing dependencies, missing virtual environment setup, broken local tooling, or other environment issues, report the exact blocker and do not present the task as fully verified.
