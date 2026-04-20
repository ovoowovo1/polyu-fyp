import React, { useEffect, useState } from 'react';
import { Table, Tag, Space, Button, message } from 'antd';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import {
  getExamSubmissions,
  getMyExamSubmissions,
} from '../../api/exam';

export default function ExamSubmissionList({ examId, mode = 'teacher', onGrade }) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [submissions, setSubmissions] = useState([]);

  const load = async () => {
    if (!examId) return;
    setLoading(true);
    try {
      const res =
        mode === 'mine'
          ? await getMyExamSubmissions(examId)
          : await getExamSubmissions(examId);
      const data = res.data.submissions || res.data.results || [];
      setSubmissions(data);
    } catch (err) {
      console.error('Load submissions failed', err);
      message.error(err.response?.data?.detail || t('exam.submissionList.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [examId, mode]);

  const columns = [];
  if (mode !== 'mine') {
    columns.push({
      title: t('exam.submissionList.student'),
      dataIndex: 'student_name',
      key: 'student_name',
      render: (_, record) =>
        record.student_name ? (
          <Space direction="vertical" size={0}>
            <span>{record.student_name}</span>
            <span style={{ color: '#888' }}>{record.student_email}</span>
          </Space>
        ) : (
          '-'
        ),
    });
  }
  columns.push({
    title: t('exam.submissionList.attemptNo'),
    dataIndex: 'attempt_no',
    key: 'attempt_no',
    width: 100,
  });
  columns.push({
    title: t('exam.submissionList.score'),
    key: 'score',
    width: 140,
    render: (_, record) => (
      <Space>
        <span>{record.score ?? '-'}</span>
        {record.total_marks ? <span>/ {record.total_marks}</span> : null}
      </Space>
    ),
  });
  columns.push({
    title: t('exam.submissionList.status'),
    dataIndex: 'status',
    key: 'status',
    width: 120,
    render: (value) => {
      const color =
        value === 'graded' ? 'green' : value === 'submitted' ? 'blue' : 'default';
      const statusText = value === 'graded' ? t('exam.submissionList.graded') : value === 'submitted' ? t('exam.submissionList.submitted') : value;
      return <Tag color={color}>{statusText}</Tag>;
    },
  });
  columns.push({
    title: t('exam.submissionList.submittedAt'),
    dataIndex: 'submitted_at',
    key: 'submitted_at',
    width: 180,
    render: (v) => (v ? dayjs(v).format('YYYY/MM/DD HH:mm') : '-'),
  });

  if (mode !== 'mine') {
    columns.push({
      title: t('exam.submissionList.actions'),
      key: 'actions',
      width: 140,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type="primary"
            onClick={() => onGrade && onGrade(record)}
          >
            {t('exam.submissionList.grade')}
          </Button>
        </Space>
      ),
    });
  }

  return (
    <Table
      rowKey="submission_id"
      dataSource={submissions}
      columns={columns}
      loading={loading}
      pagination={{ pageSize: 10 }}
    />
  );
}

