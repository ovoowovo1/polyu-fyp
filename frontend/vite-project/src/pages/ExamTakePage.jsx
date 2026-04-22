import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { Card, Spin, message, Button, Space, Typography } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

import ExamReader from '../components/Studio/ExamReader';
import { startExam } from '../api/exam';

const { Title, Text } = Typography;

export default function ExamTakePage() {
  const { t } = useTranslation();
  const { examId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();

  const presetSubmissionId = location.state?.submissionId;
  const [submissionId, setSubmissionId] = useState(presetSubmissionId || null);
  const [loading, setLoading] = useState(!presetSubmissionId);

  useEffect(() => {
    const ensureSubmission = async () => {
      if (presetSubmissionId || !examId) {
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const res = await startExam(examId);
        setSubmissionId(res.data.submission_id);
      } catch (err) {
        console.error('Start exam failed', err);
        message.error(err.response?.data?.detail || t('exam.takePage.startFailed'));
      } finally {
        setLoading(false);
      }
    };
    ensureSubmission();
  }, [examId, presetSubmissionId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spin size="large" />
      </div>
    );
  }

  if (!submissionId) {
    return (
      <div className="p-6">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
          {t('exam.reader.back')}
        </Button>
        <Card className="mt-4">
          <Title level={4}>{t('exam.takePage.cannotCreateSubmission')}</Title>
          <Text>{t('exam.takePage.cannotCreateSubmissionMessage')}</Text>
        </Card>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col">
      <ExamReader
        examId={examId}
        submissionId={submissionId}
        //onSubmitted={() => navigate('/class-list')}
        onBack={() => navigate(-1)}
      />
    </div>
  );
}

