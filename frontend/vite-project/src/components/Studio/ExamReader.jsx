import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card,
  Button,
  Space,
  Typography,
  Progress,
  message,
  Spin,
  Tag,
  Input,
} from 'antd';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { getExamById, submitExam } from '../../api/exam';
import { API_BASE_URL } from '../../config.js';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// 方案A：將後端基址與相對路徑拼接，避免從 5173 請求 /static
const toImageUrl = (p) => {
  if (!p) return '';
  return p.startsWith('http://') || p.startsWith('https://') ? p : `${API_BASE_URL}${p}`;
};

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

  // 載入考試題目
  useEffect(() => {
    const loadExam = async () => {
      setLoading(true);
      try {
        const res = await getExamById(examId, false);
        const qs = res.data.exam?.questions || [];
        setQuestions(qs);
        setExamTitle(res.data.exam?.title || 'Exam');
        setDurationMinutes(res.data.exam?.duration_minutes || null);
        setUserAnswers(new Array(qs.length).fill(null));
      } catch (err) {
        console.error('Load exam failed', err);
        message.error(err.response?.data?.detail || t('exam.reader.loadFailed'));
      } finally {
        setLoading(false);
      }
    };
    if (examId) loadExam();
  }, [examId]);

  const currentQuestion = useMemo(() => questions[currentIndex], [questions, currentIndex]);

  // Debugging: show information about the current question and render mode
  useEffect(() => {
    if (currentQuestion) {
      // eslint-disable-next-line no-console
      console.debug('ExamReader currentQuestion', {
        question_id: currentQuestion.question_id,
        type: currentQuestion.question_type,
        choices: currentQuestion.choices,
        marks: currentQuestion.marks,
        selected: selectedAnswer,
      });
    }
  }, [currentQuestion, selectedAnswer]);

  const handleAnswerSelect = (answerIndex) => {
    setSelectedAnswer(answerIndex);
    setUserAnswers((prev) => {
      const copy = [...prev];
      copy[currentIndex] = answerIndex;
      return copy;
    });
  };

  const handleTextAnswerChange = (text) => {
    setSelectedAnswer(text);
    setUserAnswers((prev) => {
      const copy = [...prev];
      copy[currentIndex] = text;
      return copy;
    });
  };

  const handleSubmitAnswer = () => {
    if (selectedAnswer === null || selectedAnswer === undefined || selectedAnswer === '') {
      message.warning(t('exam.reader.pleaseAnswer'));
      return;
    }
    const newAnswers = [...userAnswers];
    newAnswers[currentIndex] = selectedAnswer;
    setUserAnswers(newAnswers);
  };

  // 當題目切換時，同步選取狀態
  useEffect(() => {
    setSelectedAnswer(userAnswers[currentIndex] ?? null);
  }, [currentIndex, userAnswers]);

  const handleNext = () => {
    if (currentIndex < questions.length - 1) {
      setCurrentIndex(currentIndex + 1);
      setSelectedAnswer(userAnswers[currentIndex + 1]);
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
      setSelectedAnswer(userAnswers[currentIndex - 1]);
    }
  };


  const handleSubmitAll = async () => {
    if (!submissionId) {
      message.error(t('exam.reader.missingSubmissionId'));
      return;
    }
    // 確保當前題目的選擇也寫入 userAnswers
    const finalAnswers = [...userAnswers];
    if (selectedAnswer !== null && selectedAnswer !== undefined) {
      finalAnswers[currentIndex] = selectedAnswer;
      setUserAnswers(finalAnswers);
    }

    setSubmitLoading(true);
    try {
      const payload = {
        answers: finalAnswers.map((ans, idx) => {
          const q = questions[idx] || {};
          const base = {
            question_id: q.question_id,
            exam_question_id: q.exam_question_id,
          };
          // treat multiple choice with choices as index, otherwise text
          if (q.question_type === 'multiple_choice' && (q.choices || []).length > 0) {
            return { ...base, answer_index: typeof ans === 'number' ? ans : null };
          }
          // short_answer / essay / calculation or multiple_choice without choices: use answer_text
          return { ...base, answer_text: typeof ans === 'string' ? ans : '' };
        }),
        time_spent_seconds: null,
      };
      await submitExam(submissionId, payload);
      message.success(t('exam.reader.submitted'));
      if (onSubmitted) onSubmitted();
      setIsFinished(true);
    } catch (err) {
      console.error('Submit exam failed', err);
      message.error(err.response?.data?.detail || t('exam.reader.submitFailed'));
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
                src={toImageUrl(currentQuestion.image_path)}
                alt="question-visual"
                style={{ maxWidth: '100%', borderRadius: 8, border: '1px solid #eee' }}
              />
            </div>
          )}
          {(() => {
            const isMCWithChoices = currentQuestion?.question_type === 'multiple_choice' && (currentQuestion?.choices || []).length > 0;
            const isMCNoChoices = currentQuestion?.question_type === 'multiple_choice' && !(currentQuestion?.choices || []).length;
            const marks = currentQuestion?.marks || 0;
            const isShort = currentQuestion?.question_type === 'short_answer' || (isMCNoChoices && marks <= 2);
            const isLong = currentQuestion?.question_type === 'essay' || currentQuestion?.question_type === 'long_answer' || (isMCNoChoices && marks > 2);

            // Debugging helper: uncomment to log current question
            // console.debug('Rendering question:', { type: currentQuestion?.question_type, marks, choices: currentQuestion?.choices });

            if (isMCWithChoices) {
              return (currentQuestion.choices || []).map((choice, index) => {
              let className = 'w-full text-left p-4 rounded-lg border-2 transition-all';
              className += index === selectedAnswer ? ' border-blue-500 bg-blue-50' : ' border-gray-300 hover:border-blue-300';

              return (
                <button
                  key={index}
                  className={className}
                  onClick={() => handleAnswerSelect(index)}
                >
                  <div className="flex items-center justify-between">
                    <Text>{choice}</Text>
                  </div>
                </button>
              );
            })
            }
            if (isShort) {
              return (
                <TextArea
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  key="short"
                  placeholder={t('exam.reader.answerPlaceholder')}
                  value={selectedAnswer ?? ''}
                  onChange={(e) => handleTextAnswerChange(e.target.value)}
                  onPressEnter={handleSubmitAnswer}
                  allowClear
                />
              );
            }
            if (isLong) {
              // Use a larger textarea for essay/long answers; size grows with marks
              const rows = Math.min(20, Math.max(6, Math.floor(marks * 2)));
              return (
                <TextArea
                  key="essay"
                  autoSize={{ minRows: rows, maxRows: Math.min(30, rows + 10) }}
                  placeholder={t('exam.reader.longAnswerPlaceholder')}
                  value={selectedAnswer ?? ''}
                  onChange={(e) => handleTextAnswerChange(e.target.value)}
                />
              );
            }
            return (
              <TextArea
                key="default"
                autoSize={{ minRows: 3 }}
                placeholder={t('exam.reader.answerPlaceholder')}
                value={selectedAnswer ?? ''}
                onChange={(e) => handleTextAnswerChange(e.target.value)}
              />
            );
          })()}
        </Space>
      </div>

      <div className="flex  justify-end items-center p-4 border-t">
        <Space>
          <Button onClick={handlePrevious} disabled={currentIndex === 0}>
            {t('exam.reader.previous')}
          </Button>
          <Button onClick={handleNext} disabled={currentIndex === questions.length - 1}>
            {t('exam.reader.next')}
          </Button>
          <Button type="primary" onClick={handleSubmitAll} loading={submitLoading}>
            {t('exam.reader.submitAll')}
          </Button>
        </Space>
      </div>
    </div>
  );
}

