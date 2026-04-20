import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Card, Spin, Typography, Space, Tag, Button, List, message } from 'antd';
import { ArrowLeftOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { getExamById } from '../api/exam';
import DocumentsTopBar from '../components/DocumentsTopBar';

const { Title, Text, Paragraph } = Typography;

// 方案A：将后端基址与相对路径拼接，避免从 5173 请求 /static
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:3000';
const toImageUrl = (p) => {
  if (!p) return '';
  return p.startsWith('http://') || p.startsWith('https://') ? p : `${API_BASE}${p}`;
};

export default function ExamViewPage() {
  const { t } = useTranslation();
  const { examId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [exam, setExam] = useState(null);

  useEffect(() => {
    const loadExam = async () => {
      setLoading(true);
      try {
        const res = await getExamById(examId, true); // include_answers = true
        setExam(res.data.exam);
      } catch (err) {
        console.error('Load exam failed', err);
        message.error(err.response?.data?.detail || t('exam.viewPage.loadFailed'));
      } finally {
        setLoading(false);
      }
    };
    if (examId) loadExam();
  }, [examId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full p-8">
        <Spin size="large" />
      </div>
    );
  }

  if (!exam) {
    return (
      <div className="p-6">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
          {t('exam.viewPage.back')}
        </Button>
        <Card className="mt-4">
          <Title level={4}>{t('exam.viewPage.notFound')}</Title>
          <Text>{t('exam.viewPage.notFoundMessage')}</Text>
        </Card>
      </div>
    );
  }

  return (
    <>
      <DocumentsTopBar title={exam?.title || t('exam.viewPage.viewTitle')} showInvite={false} />
      <div className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
          {t('exam.viewPage.back')}
        </Button>
        <Title level={4} className="m-0">
          {exam.title || t('exam.studio.unnamedExam')}
        </Title>
        <Tag>{exam.difficulty || 'medium'}</Tag>
        <Tag color={exam.is_published ? 'green' : 'default'}>
          {exam.is_published ? t('exam.studio.published') : t('exam.studio.unpublished')}
        </Tag>
      </div>

      <Card>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Text type="secondary">{t('exam.viewPage.examId')}</Text> <Text code>{exam.id}</Text>
          </div>
          {exam.description && <Paragraph>{exam.description}</Paragraph>}
          <div className="flex gap-2">
            <Tag color="blue">{t('exam.viewPage.numQuestions', { count: exam.num_questions })}</Tag>
            {exam.total_marks !== null && <Tag color="purple">{t('exam.viewPage.totalMarks', { marks: exam.total_marks })}</Tag>}
            {exam.duration_minutes && <Tag color="magenta">{t('exam.viewPage.timeLimit', { minutes: exam.duration_minutes })}</Tag>}
          </div>

          <List
            header={<Title level={5}>{t('exam.viewPage.questions')}</Title>}
            dataSource={exam.questions || []}
            renderItem={(q, idx) => (
              <List.Item key={q.question_id || idx} style={{ alignItems: 'flex-start' }}>
                <div className="w-full space-y-2">
                  <div className="flex items-center gap-2">
                    <Text strong>
                      Q{idx + 1}. {q.question_text || q.question}
                    </Text>
                    <Tag color="geekblue">{q.bloom_level || 'general'}</Tag>
                    {q.question_type && <Tag color="cyan">{q.question_type}</Tag>}
                    {q.marks !== undefined && <Tag color="purple">{t('exam.viewPage.marks', { marks: q.marks })}</Tag>}
                  </div>

                  {q.image_path && (
                    <div>
                      <img
                        src={toImageUrl(q.image_path)}
                        alt="exam-visual"
                        style={{ maxWidth: '100%', borderRadius: 8, border: '1px solid #eee' }}
                      />
                    </div>
                  )}

                  {q.choices && q.choices.length > 0 && (
                    <div className="space-y-1">
                      {q.choices.map((c, i) => (
                        <div
                          key={i}
                          className={`p-2 rounded border ${
                            i === q.correct_answer_index ? 'border-green-500 bg-green-50' : 'border-gray-200'
                          }`}
                        >
                          <Space>
                            {String.fromCharCode(65 + i)}. {c}
                            {i === q.correct_answer_index && (
                              <CheckCircleOutlined className="text-green-600" />
                            )}
                          </Space>
                        </div>
                      ))}
                    </div>
                  )}

                  {q.model_answer && (
                    <div className="p-2 rounded border border-gray-200 bg-gray-50">
                      <Text strong>{t('exam.viewPage.modelAnswer')}</Text> {q.model_answer}
                    </div>
                  )}

                  {q.marking_scheme && q.marking_scheme.length > 0 && (
                    <div className="p-2 rounded border border-gray-200 bg-gray-50">
                      <Text strong>{t('exam.viewPage.markingScheme')}</Text>
                      <ul className="list-disc pl-5 mt-1">
                        {q.marking_scheme.map((m, i) => (
                          <li key={i}>
                            {m.criterion} ({t('exam.viewPage.marks', { marks: m.marks })}) - {m.explanation}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {q.rationale && (
                    <div className="p-2 rounded border border-gray-200 bg-gray-50">
                      <Text strong>{t('exam.viewPage.rationale')}</Text> {q.rationale}
                    </div>
                  )}
                </div>
              </List.Item>
            )}
          />
        </Space>
      </Card>
      </div>
    </>
  );
}

