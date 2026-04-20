import React, { useEffect, useState, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Table,
  Tag,
  Space,
  Button,
  Popconfirm,
  message,
  Typography,
  Card,
  Divider,
} from 'antd';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';

// ProfileMenu is provided by DocumentsTopBar
import DocumentsTopBar from '../components/DocumentsTopBar';

import {
  getExamList,
  publishExam,
  deleteExam,
  startExam,
} from '../api/exam';
import { getCurrentUser } from '../api/auth';

const { Title, Text } = Typography;

export default function ExamListPage() {
  const { t } = useTranslation();
  // dispatch is no longer needed; DocumentsTopBar handles navigation actions
  const { classId } = useParams();
  const user = getCurrentUser()
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [exams, setExams] = useState([]);

  const [userRole, setUserRole] = useState('student');
  const isTeacher = userRole === 'teacher';

  // handleLogout is now managed by DocumentsTopBar

  const loadExams = async () => {
    if (!classId) return;
    setLoading(true);
    try {
      const res = await getExamList(classId);
      setExams(res.data.exams || []);
    } catch (err) {
      console.error('Load exams failed', err);
      message.error(err.response?.data?.detail || t('exam.listPage.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExams();
  }, [classId]);

  // 取得使用者角色（優先從 token/cookie 解出的後端資訊）
  useEffect(() => {
    const fetchRole = async () => {
      try {
        const user = getCurrentUser();
        if (user?.role) {
          setUserRole(user.role);
          return;
        }
      } catch (e) {
        // ignore and fallback
      }
      // fallback: localStorage（避免舊邏輯失效）
      const cached = localStorage.getItem('role');
      setUserRole(cached || 'student');
    };
    fetchRole();
  }, [classId]);

  const handlePublish = async (examId, publish) => {
    try {
      await publishExam(examId, publish);
      message.success(publish ? t('exam.listPage.published') : t('exam.listPage.unpublished'));
      loadExams();
    } catch (err) {
      console.error('Publish exam failed', err);
      message.error(err.response?.data?.detail || t('exam.listPage.operationFailed'));
    }
  };

  const handleDelete = async (examId) => {
    try {
      await deleteExam(examId);
      message.success(t('exam.listPage.deleted'));
      loadExams();
    } catch (err) {
      console.error('Delete exam failed', err);
      message.error(err.response?.data?.detail || t('exam.listPage.deleteFailed'));
    }
  };

  const handleStart = async (examId) => {
    try {
      const res = await startExam(examId);
      const submissionId = res.data.submission_id;
      navigate(`/exam/take/${examId}`, { state: { submissionId, classId } });
    } catch (err) {
      console.error('Start exam failed', err);
      message.error(err.response?.data?.detail || t('exam.listPage.startFailed'));
    }
  };

  const columns = [
    {
      title: t('exam.listPage.table.title'),
      dataIndex: 'title',
      key: 'title',
      render: (text) => <Text strong>{text || t('exam.studio.unnamedExam')}</Text>,
    },
    {
      title: t('exam.listPage.table.numQuestions'),
      dataIndex: 'num_questions',
      key: 'num_questions',
      width: 80,
    },
    {
      title: t('exam.listPage.table.totalMarks'),
      dataIndex: 'total_marks',
      key: 'total_marks',
      width: 80,
    },
    {
      title: t('exam.listPage.table.status'),
      dataIndex: 'is_published',
      key: 'is_published',
      width: 120,
      render: (value) => (
        <Tag color={value ? 'green' : 'default'}>
          {value ? t('exam.studio.published') : t('exam.studio.unpublished')}
        </Tag>
      ),
    },
    {
      title: t('exam.listPage.table.createdAt'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (value) => (value ? dayjs(value).format('YYYY/MM/DD HH:mm') : '-'),
    },
    {
      title: t('exam.listPage.table.actions'),
      key: 'actions',
      width: 280,
      render: (_, record) => {
        const actions = [];

        if (isTeacher) {
          actions.push(
            <Button
              key="view"
              size="small"
              onClick={() => navigate(`/exam/view/${record.id}`)}
            >
              {t('exam.listPage.actions.viewExam')}
            </Button>
          );
          actions.push(
            <Button
              key="publish"
              size="small"
              type={record.is_published ? 'default' : 'primary'}
              onClick={() => handlePublish(record.id, !record.is_published)}
            >
              {record.is_published ? t('exam.listPage.actions.unpublish') : t('exam.listPage.actions.publish')}
            </Button>
          );
          actions.push(
            <Button
              key="submissions"
              size="small"
              onClick={() => navigate(`/exam/grade/${record.id}`)}
            >
              {t('exam.listPage.actions.viewSubmissions')}
            </Button>
          );
          actions.push(
            <Popconfirm
              key="delete"
              title={t('exam.listPage.actions.deleteConfirm')}
              onConfirm={() => handleDelete(record.id)}
            >
              <Button size="small" danger>
                {t('exam.listPage.actions.delete')}
              </Button>
            </Popconfirm>
          );
        } else {
          if (record.is_published) {
            actions.push(
              <Button
                key="take"
                size="small"
                type="primary"
                onClick={() => handleStart(record.id)}
              >
                {t('exam.listPage.actions.start')}
              </Button>
            );
          } else {
            actions.push(
              <Button key="disabled" size="small" disabled>
                {t('exam.listPage.actions.notPublished')}
              </Button>
            );
          }
          actions.push(
            <Button
              key="my"
              size="small"
              onClick={() => navigate(`/exam/grade/${record.id}?mode=mine`)}
            >
              {t('exam.listPage.actions.myScore')}
            </Button>
          );
        }

        return <Space>{actions}</Space>;
      },
    },
  ];

  return (
    <>
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
            <Table
              rowKey="id"
              dataSource={exams}
              columns={columns}
              loading={loading}
              pagination={{ pageSize: 10 }}
            />
          </Card>
        </div>
      </div>
    </>
  );
}

