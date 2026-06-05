import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Card,
  Divider,
  message,
  Space,
  Typography,
} from 'antd';
import { useTranslation } from 'react-i18next';

import DocumentsTopBar from '../components/DocumentsTopBar';
import { deleteExam, getExamList, publishExam, startExam } from '../api/exam';
import { getCurrentUser } from '../api/auth';
import { resolveExamListRole } from './examListPageLogic';
import ExamListTable from './ExamListTable.jsx';

const { Title, Text } = Typography;

export default function ExamListPage() {
  const { t } = useTranslation();
  const { classId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [exams, setExams] = useState([]);
  const [userRole, setUserRole] = useState('student');
  const isTeacher = userRole === 'teacher';

  const loadExams = async () => {
    if (!classId) return;
    setLoading(true);
    try {
      const response = await getExamList(classId);
      setExams(response.data.exams || []);
    } catch (error) {
      console.error('Load exams failed:', error);
      message.error(error.response?.data?.detail || t('exam.listPage.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExams();
  }, [classId]);

  useEffect(() => {
    try {
      setUserRole(resolveExamListRole({ currentUser: getCurrentUser(), storage: localStorage }));
    } catch {
      setUserRole('student');
    }
  }, [classId]);

  const handlePublish = async (examId, publish) => {
    try {
      await publishExam(examId, publish);
      message.success(publish ? t('exam.listPage.published') : t('exam.listPage.unpublished'));
      loadExams();
    } catch (error) {
      console.error('Publish exam failed:', error);
      message.error(error.response?.data?.detail || t('exam.listPage.operationFailed'));
    }
  };

  const handleDelete = async (examId) => {
    try {
      await deleteExam(examId);
      message.success(t('exam.listPage.deleted'));
      loadExams();
    } catch (error) {
      console.error('Delete exam failed:', error);
      message.error(error.response?.data?.detail || t('exam.listPage.deleteFailed'));
    }
  };

  const handleStart = async (examId) => {
    try {
      const response = await startExam(examId);
      navigate(`/exam/take/${examId}`, { state: { submissionId: response.data.submission_id, classId } });
    } catch (error) {
      console.error('Start exam failed:', error);
      message.error(error.response?.data?.detail || t('exam.listPage.startFailed'));
    }
  };

  return (
    <div>
      <DocumentsTopBar title={t('exam.listPage.title')} showInvite={false} />
      <div className="p-4">
        <Card>
          <div className="flex justify-between items-center mb-3">
            <div>
              <Title level={3} style={{ margin: 0 }}>
                {t('exam.listPage.title')}
              </Title>
              <Text type="secondary">{t('exam.listPage.classId')}: {classId}</Text>
            </div>
            <Space>
              <Button onClick={loadExams}>{t('exam.listPage.refresh')}</Button>
            </Space>
          </div>
          <Divider style={{ margin: '12px 0' }} />
          <ExamListTable
            t={t}
            exams={exams}
            loading={loading}
            isTeacher={isTeacher}
            onNavigate={navigate}
            onPublish={handlePublish}
            onDelete={handleDelete}
            onStart={handleStart}
          />
        </Card>
      </div>
    </div>
  );
}
