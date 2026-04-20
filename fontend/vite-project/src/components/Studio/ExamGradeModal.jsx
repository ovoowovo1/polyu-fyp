import React, { useEffect, useState } from 'react';
import { Modal, InputNumber, Input, List, Typography, Space, Tag, message, Button, Spin, Tooltip } from 'antd';
import { useTranslation } from 'react-i18next';
import { RobotOutlined } from '@ant-design/icons';
import { gradeSubmission, aiGradeSubmission } from '../../api/exam';

const { Text, Paragraph } = Typography;

export default function ExamGradeModal({ open, onClose, submission, onGraded }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState([]);
  const [saving, setSaving] = useState(false);
  const [aiGrading, setAiGrading] = useState(false);
  const [teacherComment, setTeacherComment] = useState('');
  const [aiGradedFields, setAiGradedFields] = useState(new Set()); // Track which fields were AI-graded

  useEffect(() => {
    if (submission) {
      setAnswers(submission.answers || []);
      setTeacherComment(submission.teacher_comment || '');
      setAiGradedFields(new Set()); // Reset AI graded fields when submission changes
    }
  }, [submission]);

  const handleAiGrade = async () => {
    if (!submission) return;
    setAiGrading(true);
    try {
      const res = await aiGradeSubmission(submission.submission_id);
      const gradedAnswers = res.data.graded_answers || [];
      
      // Update answers with AI grading results
      const newAiGradedFields = new Set();
      setAnswers((prev) => {
        return prev.map((a) => {
          const aiResult = gradedAnswers.find(
            (g) => g.answer_id === a.id || g.exam_question_id === a.exam_question_id
          );
          if (aiResult && aiResult.ai_graded) {
            newAiGradedFields.add(a.id);
            return {
              ...a,
              marks_earned: aiResult.marks_earned,
              teacher_feedback: aiResult.teacher_feedback,
            };
          }
          return a;
        });
      });
      setAiGradedFields(newAiGradedFields);

      // Update overall comment from AI response
      if (res.data.submission && res.data.submission.teacher_comment) {
        setTeacherComment(res.data.submission.teacher_comment);
      }

      message.success(t('exam.gradeModal.aiGradeSuccess', 'AI grading completed. Please review and save.'));
    } catch (err) {
      console.error('AI grading failed', err);
      message.error(err.response?.data?.detail || t('exam.gradeModal.aiGradeFailed', 'AI grading failed'));
    } finally {
      setAiGrading(false);
    }
  };

  const handleChangeMark = (answerId, value) => {
    setAnswers((prev) =>
      prev.map((a) => (a.id === answerId ? { ...a, marks_earned: value } : a))
    );
  };

  const handleChangeFeedback = (answerId, value) => {
    setAnswers((prev) =>
      prev.map((a) => (a.id === answerId ? { ...a, teacher_feedback: value } : a))
    );
  };

  const handleSubmit = async () => {
    if (!submission) return;
    setSaving(true);
    try {
      const payload = {
        answers_grades: answers.map((a) => ({
          answer_id: a.id,
          exam_question_id: a.exam_question_id,
          marks_earned: a.marks_earned ?? 0,
          teacher_feedback: a.teacher_feedback,
        })),
        teacher_comment: teacherComment,
      };
      await gradeSubmission(submission.submission_id, payload);
      message.success(t('exam.gradeModal.graded'));
      if (onGraded) onGraded();
      onClose();
    } catch (err) {
      console.error('Grade failed', err);
      message.error(err.response?.data?.detail || t('exam.gradeModal.gradeFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title={
        <Space>
          {t('exam.gradeModal.title')}
          <Tooltip title={t('exam.gradeModal.aiGradeTooltip', 'Use AI to auto-grade short answer and essay questions')}>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              onClick={handleAiGrade}
              loading={aiGrading}
              disabled={saving}
              size="small"
            >
              {t('exam.gradeModal.aiGrade', 'AI Grade')}
            </Button>
          </Tooltip>
        </Space>
      }
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={saving}
      width={900}
      okText={t('exam.gradeModal.submit')}
      cancelText={t('common.cancel')}
    >
      <Spin spinning={aiGrading} tip={t('exam.gradeModal.aiGrading', 'AI is grading...')}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Text strong>{t('exam.gradeModal.student')}</Text>: {submission?.student_name} ({submission?.student_email}){' '}
            {submission?.score !== null && <Tag color="blue">{t('exam.gradeModal.currentScore')} {submission?.score}</Tag>}
            {submission?.grading_source === 'ai' && <Tag color="purple">AI Graded</Tag>}
          </div>

          <List
            dataSource={answers}
            renderItem={(item, index) => {
              const q = item.question_snapshot || {};
              const choices = q.choices || [];
              const selected = item.selected_options && item.selected_options[0];
              const isAiGraded = aiGradedFields.has(item.id);
              return (
              <List.Item
                key={item.id || index}
                style={{ alignItems: 'flex-start' }}
              >
                <div style={{ width: '100%' }}>
                  <Paragraph strong>
                    Q{index + 1}. {q.question_text || q.question}
                  </Paragraph>
                  {choices.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      {choices.map((c, idx) => (
                        <Tag
                          key={idx}
                          color={
                            idx === q.correct_answer_index
                              ? 'green'
                              : idx === selected
                              ? 'blue'
                              : 'default'
                          }
                        >
                          {String.fromCharCode(65 + idx)}. {c}
                        </Tag>
                      ))}
                    </div>
                  )}
                  {(() => {
                    const hasAnswerText = !!item.answer_text;
                    if (choices.length > 0) {
                      return (
                        <div style={{ marginBottom: 8 }}>
                          <Text type="secondary">{t('exam.gradeModal.studentAnswer')}：</Text>
                          {selected !== undefined && selected !== null ? (
                            <Tag color="blue">{String.fromCharCode(65 + selected)}</Tag>
                          ) : (
                            <Text type="secondary">{t('exam.gradeModal.notAnswered')}</Text>
                          )}
                        </div>
                      );
                    }

                  })()}
                  {/* Show marking scheme (criteria and marks) to assist teacher grading */}
                  {(q.marking_scheme || []).length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <Text type="secondary">{t('exam.gradeModal.referenceCriteria')}：</Text>
                      <div style={{ marginTop: 6 }}>
                        {(q.marking_scheme || []).map((m, idx) => (
                          <div key={idx} style={{ marginBottom: 6 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <Tag color="gold">{m.marks} {t('exam.gradeModal.marks')}</Tag>
                              <Text>{m.criterion}</Text>
                            </div>
                          </div>
                        ))}
                        {typeof q.marks === 'number' && (
                          <div style={{ marginTop: 4 }}>
                            <Text type="secondary">{t('exam.gradeModal.totalMarks')}：</Text> <Text strong>{q.marks} {t('exam.gradeModal.marks')}</Text>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {/* Show full paragraph for all non-choice answers (short and long) */}
                  {choices.length === 0 && item.answer_text && (
                    <Paragraph>
                      <Text type="secondary">{t('exam.gradeModal.studentAnswerText')}：</Text> {item.answer_text}
                    </Paragraph>
                  )}
                  <Space style={{ width: '100%' }} wrap>
                    <div>
                      <Text>{t('exam.gradeModal.score')}</Text>
                      <InputNumber
                        min={0}
                        max={q.marks}
                        placeholder={q.marks ? t('exam.gradeModal.maxScore', { max: q.marks }) : ''}
                        value={item.marks_earned}
                        onChange={(v) => handleChangeMark(item.id, v)}
                        style={{ marginLeft: 8, width: 120 }}
                      />
                      {isAiGraded && <Tag color="purple" style={{ marginLeft: 8 }}><RobotOutlined /> AI</Tag>}
                    </div>
                    <div style={{ flex: 1, minWidth: 240 }}>
                      <Text>{t('exam.gradeModal.teacherFeedback')}</Text>
                      <Input.TextArea
                        rows={2}
                        value={item.teacher_feedback}
                        onChange={(e) => handleChangeFeedback(item.id, e.target.value)}
                        placeholder={t('exam.gradeModal.feedbackPlaceholder')}
                      />
                    </div>
                  </Space>
                </div>
              </List.Item>
            );
          }}
        />

        <div>
          <Text strong>{t('exam.gradeModal.overallComment')}</Text>
          <Input.TextArea
            rows={3}
            value={teacherComment}
            onChange={(e) => setTeacherComment(e.target.value)}
            placeholder={t('exam.gradeModal.overallCommentPlaceholder')}
          />
        </div>
        </Space>
      </Spin>
    </Modal>
  );
}

