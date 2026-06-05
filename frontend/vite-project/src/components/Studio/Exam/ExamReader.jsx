import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  Input,
  message,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { useTranslation } from 'react-i18next';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { getExamById, submitExam } from '../../../api/exam';
import { API_BASE_URL } from '../../../config.js';
import {
  buildExamSubmitPayload,
  createEmptyExamAnswers,
  examImageUrl,
  nextExamIndex,
  previousExamIndex,
  questionInputMode,
  restoreExamAnswer,
} from './examReaderLogic.js';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function ExamReader({ examId, submissionId, onSubmitted, onBack }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [questions, setQuestions] = useState([]);
  const [examTitle, setExamTitle] = useState('');
  const [durationMinutes, setDurationMinutes] = useState(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState(null);
  const [userAnswers, setUserAnswers] = useState([]);
  const [isFinished, setIsFinished] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);

  useEffect(() => {
    const loadExam = async () => {
      setLoading(true);
      try {
        const response = await getExamById(examId, false);
        const loadedQuestions = response.data.exam?.questions || [];
        setQuestions(loadedQuestions);
        setExamTitle(response.data.exam?.title || 'Exam');
        setDurationMinutes(response.data.exam?.duration_minutes || null);
        setUserAnswers(createEmptyExamAnswers(loadedQuestions.length));
      } catch (error) {
        console.error('Load exam failed:', error);
        message.error(error.response?.data?.detail || t('exam.reader.loadFailed'));
      } finally {
        setLoading(false);
      }
    };
    if (examId) loadExam();
  }, [examId]);

  const currentQuestion = useMemo(() => questions[currentIndex], [questions, currentIndex]);

  useEffect(() => {
    setSelectedAnswer(restoreExamAnswer(userAnswers, currentIndex));
  }, [currentIndex, userAnswers]);

  const updateCurrentAnswer = (answer) => {
    setSelectedAnswer(answer);
    setUserAnswers((previous) => {
      const next = [...previous];
      next[currentIndex] = answer;
      return next;
    });
  };

  const handleSubmitAnswer = () => {
    if (selectedAnswer === null || selectedAnswer === undefined || selectedAnswer === '') {
      message.warning(t('exam.reader.pleaseAnswer'));
      return;
    }
    updateCurrentAnswer(selectedAnswer);
  };

  const handleNext = () => {
    setCurrentIndex(nextExamIndex(currentIndex, questions));
  };

  const handlePrevious = () => {
    setCurrentIndex(previousExamIndex(currentIndex));
  };

  const handleSubmitAll = async () => {
    if (!submissionId) {
      message.error(t('exam.reader.missingSubmissionId'));
      return;
    }

    const finalAnswers = [...userAnswers];
    if (selectedAnswer !== null && selectedAnswer !== undefined) {
      finalAnswers[currentIndex] = selectedAnswer;
      setUserAnswers(finalAnswers);
    }

    setSubmitLoading(true);
    try {
      await submitExam(submissionId, buildExamSubmitPayload({ questions, userAnswers: finalAnswers }));
      message.success(t('exam.reader.submitted'));
      onSubmitted?.();
      setIsFinished(true);
    } catch (error) {
      console.error('Submit exam failed:', error);
      message.error(error.response?.data?.detail || t('exam.reader.submitFailed'));
    } finally {
      setSubmitLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spin size="large" />
      </div>
    );
  }

  if (!questions.length) {
    return (
      <div className="p-6">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack || (() => navigate(-1))}>
          {t('exam.reader.back')}
        </Button>
        <Card className="mt-4">
          <Title level={4}>{t('exam.reader.noQuestions')}</Title>
          <Text>{t('exam.reader.contactTeacher')}</Text>
        </Card>
      </div>
    );
  }

  const progress = Math.round(((currentIndex + 1) / questions.length) * 100);
  const inputMode = questionInputMode(currentQuestion);
  const marks = currentQuestion?.marks || 0;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b">
        <Space>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack || (() => navigate(-1))} />
          <Title level={5} className="m-0">
            {examTitle}
          </Title>
          {durationMinutes ? <Tag color="purple">{t('exam.reader.timeLimit', { minutes: durationMinutes })}</Tag> : null}
        </Space>
        <Text type="secondary">
          {currentIndex + 1} / {questions.length}
        </Text>
      </div>

      <Progress percent={progress} showInfo={false} strokeColor="#1677ff" />

      <div className="flex-1 overflow-y-auto p-6">
        <Card className="mb-4">
          <Title level={4}>{currentQuestion.question_text || currentQuestion.question}</Title>
        </Card>

        <Space direction="vertical" className="w-full" size="middle">
          {currentQuestion?.image_path && (
            <div>
              <img
                src={examImageUrl(currentQuestion.image_path, API_BASE_URL)}
                alt="question visual"
                style={{ maxWidth: '100%', borderRadius: 8, border: '1px solid #eee' }}
              />
            </div>
          )}

          {inputMode === 'multiple_choice' && (currentQuestion.choices || []).map((choice, index) => {
            let className = 'w-full text-left p-4 rounded-lg border-2 transition-all';
            className += index === selectedAnswer ? ' border-blue-500 bg-blue-50' : ' border-gray-300 hover:border-blue-300';
            return (
              <button key={index} className={className} onClick={() => updateCurrentAnswer(index)}>
                <div className="flex items-center justify-between">
                  <Text>{choice}</Text>
                </div>
              </button>
            );
          })}

          {inputMode === 'short_answer' && (
            <TextArea
              autoSize={{ minRows: 2, maxRows: 6 }}
              placeholder={t('exam.reader.answerPlaceholder')}
              value={selectedAnswer ?? ''}
              onChange={(event) => updateCurrentAnswer(event.target.value)}
              onPressEnter={handleSubmitAnswer}
              allowClear
            />
          )}

          {inputMode === 'essay' && (
            <TextArea
              autoSize={{ minRows: Math.min(20, Math.max(6, Math.floor(marks * 2))), maxRows: Math.min(30, Math.max(6, Math.floor(marks * 2)) + 10) }}
              placeholder={t('exam.reader.longAnswerPlaceholder')}
              value={selectedAnswer ?? ''}
              onChange={(event) => updateCurrentAnswer(event.target.value)}
            />
          )}

          {inputMode === 'text' && (
            <TextArea
              autoSize={{ minRows: 3 }}
              placeholder={t('exam.reader.answerPlaceholder')}
              value={selectedAnswer ?? ''}
              onChange={(event) => updateCurrentAnswer(event.target.value)}
            />
          )}
        </Space>
      </div>

      <div className="flex justify-end items-center p-4 border-t">
        <Space>
          <Button onClick={handlePrevious} disabled={currentIndex === 0}>
            {t('exam.reader.previous')}
          </Button>
          <Button onClick={handleNext} disabled={currentIndex === questions.length - 1}>
            {t('exam.reader.next')}
          </Button>
          <Button type="primary" onClick={handleSubmitAll} loading={submitLoading} disabled={isFinished}>
            {t('exam.reader.submitAll')}
          </Button>
        </Space>
      </div>
    </div>
  );
}
