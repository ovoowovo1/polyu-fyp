import React, { useEffect, useState } from 'react';
import { Button, Input, InputNumber, List, message, Modal, Space, Spin, Tag, Tooltip, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import { RobotOutlined } from '@ant-design/icons';
import { aiGradeSubmission, gradeSubmission } from '../../../api/exam';
import { buildManualGradePayload, mergeAiGradingResults } from './examGradingLogic.js';

const { Text, Paragraph } = Typography;

export default function ExamGradeModal({ open, onClose, submission, onGraded }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState([]);
  const [saving, setSaving] = useState(false);
  const [aiGrading, setAiGrading] = useState(false);
  const [teacherComment, setTeacherComment] = useState('');
  const [aiGradedFields, setAiGradedFields] = useState(new Set());

  useEffect(() => {
    if (submission) {
      setAnswers(submission.answers || []);
      setTeacherComment(submission.teacher_comment || '');
      setAiGradedFields(new Set());
    }
  }, [submission]);

  const handleAiGrade = async () => {
    if (!submission) return;
    setAiGrading(true);
    try {
      const response = await aiGradeSubmission(submission.submission_id);
      const merged = mergeAiGradingResults(answers, response.data.graded_answers || []);
      setAnswers(merged.answers);
      setAiGradedFields(merged.aiGradedIds);
      if (response.data.submission?.teacher_comment) {
        setTeacherComment(response.data.submission.teacher_comment);
      }
      message.success(t('exam.gradeModal.aiGradeSuccess', 'AI grading completed. Please review and save.'));
    } catch (error) {
      console.error('AI grading failed:', error);
      message.error(error.response?.data?.detail || t('exam.gradeModal.aiGradeFailed', 'AI grading failed'));
    } finally {
      setAiGrading(false);
    }
  };

  const handleChangeMark = (answerId, value) => {
    setAnswers((previous) =>
      previous.map((answer) => (answer.id === answerId ? { ...answer, marks_earned: value } : answer)),
    );
  };

  const handleChangeFeedback = (answerId, value) => {
    setAnswers((previous) =>
      previous.map((answer) => (answer.id === answerId ? { ...answer, teacher_feedback: value } : answer)),
    );
  };

  const handleSubmit = async () => {
    if (!submission) return;
    setSaving(true);
    try {
      await gradeSubmission(submission.submission_id, buildManualGradePayload({ answers, teacherComment }));
      message.success(t('exam.gradeModal.graded'));
      onGraded?.();
      onClose();
    } catch (error) {
      console.error('Grade submission failed:', error);
      message.error(error.response?.data?.detail || t('exam.gradeModal.gradeFailed'));
    } finally {
      setSaving(false);
    }
  };

  const renderAnswer = (item, index) => {
    const question = item.question_snapshot || {};
    const choices = question.choices || [];
    const selected = item.selected_options?.[0];
    const isAiGraded = aiGradedFields.has(item.id);

    return (
      <List.Item key={item.id || index} style={{ alignItems: 'flex-start' }}>
        <div style={{ width: '100%' }}>
          <Paragraph strong>
            Q{index + 1}. {question.question_text || question.question}
          </Paragraph>

          {choices.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              {choices.map((choice, choiceIndex) => (
                <Tag
                  key={choiceIndex}
                  color={
                    choiceIndex === question.correct_answer_index
                      ? 'green'
                      : choiceIndex === selected
                        ? 'blue'
                        : 'default'
                  }
                >
                  {String.fromCharCode(65 + choiceIndex)}. {choice}
                </Tag>
              ))}
            </div>
          )}

          {choices.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary">{t('exam.gradeModal.studentAnswer')}: </Text>
              {selected !== undefined && selected !== null ? (
                <Tag color="blue">{String.fromCharCode(65 + selected)}</Tag>
              ) : (
                <Text type="secondary">{t('exam.gradeModal.notAnswered')}</Text>
              )}
            </div>
          )}

          {(question.marking_scheme || []).length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary">{t('exam.gradeModal.referenceCriteria')}: </Text>
              <div style={{ marginTop: 6 }}>
                {(question.marking_scheme || []).map((markingItem, markingIndex) => (
                  <div key={markingIndex} style={{ marginBottom: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Tag color="gold">{markingItem.marks} {t('exam.gradeModal.marks')}</Tag>
                      <Text>{markingItem.criterion}</Text>
                    </div>
                  </div>
                ))}
                {typeof question.marks === 'number' && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary">{t('exam.gradeModal.totalMarks')}: </Text>
                    <Text strong>{question.marks} {t('exam.gradeModal.marks')}</Text>
                  </div>
                )}
              </div>
            </div>
          )}

          {choices.length === 0 && item.answer_text && (
            <Paragraph>
              <Text type="secondary">{t('exam.gradeModal.studentAnswerText')}: </Text>
              {item.answer_text}
            </Paragraph>
          )}

          <Space style={{ width: '100%' }} wrap>
            <div>
              <Text>{t('exam.gradeModal.score')}</Text>
              <InputNumber
                min={0}
                max={question.marks}
                placeholder={question.marks ? t('exam.gradeModal.maxScore', { max: question.marks }) : ''}
                value={item.marks_earned}
                onChange={(value) => handleChangeMark(item.id, value)}
                style={{ marginLeft: 8, width: 120 }}
              />
              {isAiGraded && <Tag color="purple" style={{ marginLeft: 8 }}><RobotOutlined /> AI</Tag>}
            </div>
            <div style={{ flex: 1, minWidth: 240 }}>
              <Text>{t('exam.gradeModal.teacherFeedback')}</Text>
              <Input.TextArea
                rows={2}
                value={item.teacher_feedback}
                onChange={(event) => handleChangeFeedback(item.id, event.target.value)}
                placeholder={t('exam.gradeModal.feedbackPlaceholder')}
              />
            </div>
          </Space>
        </div>
      </List.Item>
    );
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

          <List dataSource={answers} renderItem={renderAnswer} />

          <div>
            <Text strong>{t('exam.gradeModal.overallComment')}</Text>
            <Input.TextArea
              rows={3}
              value={teacherComment}
              onChange={(event) => setTeacherComment(event.target.value)}
              placeholder={t('exam.gradeModal.overallCommentPlaceholder')}
            />
          </div>
        </Space>
      </Spin>
    </Modal>
  );
}
