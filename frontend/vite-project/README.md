# Web Frontend

React + Vite web client for the PolyU FYP learning workspace. It connects to the FastAPI backend for authentication, document ingestion, retrieval chat, quiz workflows, exam generation, grading, and classroom management.

## Features

- Authenticated teacher/student workspace with protected routes.
- Document upload, source list management, and source reading.
- Retrieval chat with streaming progress and citation display.
- Quiz generation, quiz reading, submissions, and result review.
- Exam generation, exam viewing, publishing, taking, PDF links, and grading.
- English and Traditional Chinese translations via i18next.

## Pages

- `LoginPage.jsx`: login and registration entrypoint.
- `DocumentsPage.jsx`: document workspace, source upload, and chat surface.
- `ClassListPage.jsx`: class ownership and enrollment flows.
- `ExamListPage.jsx`, `ExamViewPage.jsx`, `ExamTakePage.jsx`, `ExamGradePage.jsx`: exam lifecycle screens.
- `EditQuiz.jsx`: quiz creation/editing and quiz reader entrypoint.

## Env Setup

Create `frontend/vite-project/.env` from `.env.example`:

```powershell
VITE_API_BASE_URL=http://localhost:3000
```

Local development and tests can fall back to `http://localhost:3000`. Production builds must set `VITE_API_BASE_URL` to the deployed backend URL; missing production configuration fails fast instead of silently calling the user's local machine.

## Test And Build Commands

Run commands from `frontend/vite-project`:

```powershell
npm install
node --test
npm run build
npm run dev
```

## Folder Structure

- `src/api`: backend API clients and request helpers.
- `src/components`: shared UI components and workflow-specific component groups.
- `src/pages`: route-level page components.
- `src/redux`: Redux store and slices.
- `src/hooks`: reusable React hooks.
- `src/utils`: streaming, layout, request, and rendering utilities.
- `src/i18n`: translation setup and locale files.
- `src/testing`: lightweight test helpers for Node-based frontend tests.
