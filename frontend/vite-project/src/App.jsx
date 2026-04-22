import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhTW from 'antd/locale/zh_TW';

import DocumentsPage from './pages/DocumentsPage';
import LoginPage from './pages/LoginPage';
import ClassListPage from './pages/ClassListPage';
import EditQuiz from './pages/EditQuiz';
import ExamListPage from './pages/ExamListPage';
import ExamTakePage from './pages/ExamTakePage';
import ExamGradePage from './pages/ExamGradePage';
import ExamViewPage from './pages/ExamViewPage';
import ExamEdit from './components/Studio/Exam/Exam.jsx';
import ProtectedRoute from './components/ProtectedRoute';

export default function App() {
  return (
    <ConfigProvider locale={zhTW}>
      <Router>
        <div className='h-screen flex flex-col'>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/documents/:classId" element={<DocumentsPage />} />
              <Route path="/class-list" element={<ClassListPage />} />
              <Route path="/quiz/new" element={<EditQuiz />} />
              <Route path="/quiz/edit/:quizId" element={<EditQuiz />} />
              <Route path="/exam" element={<ExamEdit />} />
              <Route path="/exam/list/:classId" element={<ExamListPage />} />
              <Route path="/exam/take/:examId" element={<ExamTakePage />} />
              <Route path="/exam/grade/:examId" element={<ExamGradePage />} />
              <Route path="/exam/view/:examId" element={<ExamViewPage />} />
            </Route>
            <Route path="/" element={<LoginPage />} />
          </Routes>
        </div>
      </Router>
    </ConfigProvider>
  );
}
