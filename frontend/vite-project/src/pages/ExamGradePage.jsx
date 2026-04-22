import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Card, Button, Space, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import { ArrowLeftOutlined } from '@ant-design/icons';

import ExamSubmissionList from '../components/Studio/ExamSubmissionList';
import ExamGradeModal from '../components/Studio/ExamGradeModal';
import DocumentsTopBar from '../components/DocumentsTopBar';
import { getCurrentUser } from '../api/auth';

const { Title, Text } = Typography;

export default function ExamGradePage() {
  const { t } = useTranslation();
  const { examId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const modeParam = searchParams.get('mode') === 'mine' ? 'mine' : 'teacher';
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  // start with null so we can avoid making assumptions (and avoid triggering `my-submissions` for teachers)
  const [userRole, setUserRole] = useState(null);
  const isTeacher = userRole === 'teacher';

  useEffect(() => {
    const loadRole = () => {
      try {
        const u = getCurrentUser();
        if (u?.role) {
          setUserRole(u.role);
          return;
        }
      } catch (e) {
        /* ignore */
      }
      const cached = localStorage.getItem('role');
      setUserRole(cached || 'student');
    };
    loadRole();
  }, []);

  const handleGrade = (submission) => {
    setSelectedSubmission(submission);
    setModalOpen(true);
  };

  const handleGraded = () => {
    setModalOpen(false);
    setRefreshKey((k) => k + 1);
  };

  return (
    <>
      <DocumentsTopBar title={t('exam.gradePage.title')} showInvite={false} />
      <div className="p-4">
        <Card>
          <div className="flex justify-between items-center mb-3">
            <Space>
              <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
                {t('exam.reader.back')}
              </Button>
            <div>
              <Title level={4} style={{ margin: 0 }}>
                {t('exam.gradePage.title')}
              </Title>
              <Text type="secondary">{t('exam.gradePage.examId')}: {examId}</Text>
            </div>
            </Space>
            <Space>
              <Button onClick={() => setRefreshKey((k) => k + 1)}>{t('exam.gradePage.refresh')}</Button>
            </Space>
          </div>
        {userRole === null ? (
          <div style={{ padding: 12 }}>{t('common.loading')}</div>
        ) : (
          <ExamSubmissionList
            key={refreshKey}
            examId={examId}
            mode={isTeacher ? 'teacher' : modeParam === 'mine' ? 'mine' : 'teacher'}
            onGrade={handleGrade}
          />
        )}
      </Card>

      <ExamGradeModal
        open={modalOpen}
        submission={selectedSubmission}
        onClose={() => setModalOpen(false)}
        onGraded={handleGraded}
      />
      </div>
    </>
  );
}

