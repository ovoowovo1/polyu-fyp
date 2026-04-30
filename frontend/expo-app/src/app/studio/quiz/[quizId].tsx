import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  Text,
  View,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';

import { generateQuizFeedback, getMyQuizResult, getQuizById, submitQuiz } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { colors, commonStyles } from '@/lib/styles';
import type { QuizDetail, QuizQuestion, QuizResultSummary } from '@/lib/types';

export default function QuizDetailScreen() {
  const { quizId } = useLocalSearchParams<{ quizId: string }>();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [quiz, setQuiz] = useState<QuizDetail | null>(null);
  const [result, setResult] = useState<QuizResultSummary | null>(null);
  const [feedback, setFeedback] = useState('');
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState<number | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [userAnswers, setUserAnswers] = useState<(number | null)[]>([]);
  const [isFinished, setIsFinished] = useState(false);
  const [finalScore, setFinalScore] = useState<{ correct: number; total: number; percentage: number } | null>(null);
  const isTeacher = user?.role === 'teacher';

  useEffect(() => {
    if (!quizId) {
      return;
    }

    async function load() {
      setLoading(true);
      try {
        const [quizResult, myResult] = await Promise.all([
          getQuizById(quizId),
          isTeacher ? Promise.resolve({ submission: null }) : getMyQuizResult(quizId),
        ]);
        const nextQuiz = quizResult.quiz;
        setQuiz(nextQuiz);
        setResult(myResult.submission);
        setUserAnswers(new Array(nextQuiz.questions?.length ?? 0).fill(null));
      } catch (error) {
        Alert.alert('Quiz load failed', error instanceof Error ? error.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [isTeacher, quizId]);

  const currentQuestion = useMemo(
    () => quiz?.questions?.[currentIndex] || null,
    [currentIndex, quiz?.questions],
  );

  const handleAnswerSelect = (answerIndex: number) => {
    if (showResult) {
      return;
    }
    setSelectedAnswer(answerIndex);
  };

  const handleSubmitAnswer = () => {
    if (selectedAnswer === null) {
      Alert.alert('Select an answer', 'Please select an answer before submitting.');
      return;
    }

    setUserAnswers((current) => {
      const next = [...current];
      next[currentIndex] = selectedAnswer;
      return next;
    });
    setShowResult(true);
  };

  const handleNext = () => {
    if (!quiz?.questions?.length) {
      return;
    }
    if (currentIndex < quiz.questions.length - 1) {
      setCurrentIndex((value) => value + 1);
      return;
    }
    setIsFinished(true);
  };

  const handlePrevious = () => {
    if (currentIndex === 0) {
      return;
    }
    setCurrentIndex((value) => value - 1);
  };

  const requestFeedback = useCallback(async (score: { correct: number; total: number; percentage: number }) => {
    if (!quizId || !quiz?.questions?.length) {
      return;
    }

    setFeedbackLoading(true);
    setFeedbackError(null);
    try {
      const feedbackResponse = await generateQuizFeedback(
        quizId,
        buildQuizFeedbackPayload(quiz, userAnswers, score),
      );
      setFeedback(feedbackResponse.feedback || '');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setFeedbackError(message);
    } finally {
      setFeedbackLoading(false);
    }
  }, [quiz, quizId, userAnswers]);

  const requestSubmit = useCallback(async (score: { correct: number; total: number; percentage: number }) => {
    if (!quizId || !quiz?.questions?.length || isTeacher) {
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitQuiz(quizId, {
        answers: userAnswers.map((answer, index) => ({
          question_index: index,
          answer_index: answer,
        })),
        score: score.correct,
        total_questions: score.total,
      });
      setResult({
        score: score.correct,
        total_questions: score.total,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setSubmitError(message);
    } finally {
      setSubmitting(false);
    }
  }, [isTeacher, quiz, quizId, userAnswers]);

  useEffect(() => {
    if (!quiz?.questions?.length) {
      return;
    }

    if (isFinished) {
      const score = calculateScore(quiz.questions, userAnswers);
      setFinalScore(score);
      if (isTeacher) {
        setResult({
          score: score.correct,
          total_questions: score.total,
        });
      }
      void requestSubmit(score);
      void requestFeedback(score);
      return;
    }

    setSelectedAnswer(userAnswers[currentIndex]);
    setShowResult(userAnswers[currentIndex] !== null);
  }, [currentIndex, isFinished, isTeacher, quiz?.questions, requestFeedback, requestSubmit, userAnswers]);

  const retrySubmit = useCallback(() => {
    if (!finalScore || isTeacher) {
      return;
    }
    void requestSubmit(finalScore);
  }, [finalScore, isTeacher, requestSubmit]);

  const retryFeedback = useCallback(() => {
    if (!finalScore) {
      return;
    }
    void requestFeedback(finalScore);
  }, [finalScore, requestFeedback]);

  const restartQuiz = () => {
    setCurrentIndex(0);
    setSelectedAnswer(null);
    setShowResult(false);
    setUserAnswers(new Array(quiz?.questions?.length ?? 0).fill(null));
    setIsFinished(false);
    setFeedback('');
    setSubmitError(null);
    setFeedbackError(null);
    setFeedbackLoading(false);
    setSubmitting(false);
    setFinalScore(null);
    setResult(null);
  };

  if (loading) {
    return (
      <View style={[commonStyles.fullScreen, commonStyles.emptyBox]}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (!quiz || !quiz.questions?.length) {
    return (
      <View style={[commonStyles.fullScreen, commonStyles.emptyBox]}>
        <Text selectable style={commonStyles.emptyTitle}>Quiz not found</Text>
      </View>
    );
  }

  if (isFinished && finalScore) {
    return (
      <ScrollView contentInsetAdjustmentBehavior="automatic" contentContainerStyle={commonStyles.listContent}>
        <View style={[commonStyles.card, { alignItems: 'center' }]}>
          <Text selectable style={commonStyles.title}>Quiz Completed</Text>
          <Text selectable style={[commonStyles.title, { color: colors.success }]}>
            {finalScore.correct}/{finalScore.total}
          </Text>
          <Text selectable style={commonStyles.subtitle}>{finalScore.percentage}%</Text>
        </View>

        {!isTeacher && (
          <View style={commonStyles.progressCard}>
            <Text selectable style={commonStyles.label}>Submission</Text>
            {submitting ? (
              <ActivityIndicator color={colors.primary} />
            ) : submitError ? (
              <>
                <Text selectable style={{ color: colors.danger, fontSize: 13 }}>{submitError}</Text>
                <View style={{ marginTop: 10 }}>
                  <Pressable accessibilityRole="button" onPress={retrySubmit} style={commonStyles.secondaryButton}>
                    <Text style={commonStyles.secondaryButtonText}>Try again</Text>
                  </Pressable>
                </View>
              </>
            ) : (
              <Text selectable style={commonStyles.muted}>
                {result ? 'Quiz result submitted.' : 'Preparing submission...'}
              </Text>
            )}
          </View>
        )}

        <View style={commonStyles.progressCard}>
          <Text selectable style={commonStyles.label}>AI feedback</Text>
          {feedbackLoading ? (
            <ActivityIndicator color={colors.primary} />
          ) : feedbackError ? (
            <>
              <Text selectable style={{ color: colors.danger, fontSize: 13 }}>{feedbackError}</Text>
              <View style={{ marginTop: 10 }}>
                <Pressable accessibilityRole="button" onPress={retryFeedback} style={commonStyles.secondaryButton}>
                  <Text style={commonStyles.secondaryButtonText}>Try again</Text>
                </Pressable>
              </View>
            </>
          ) : (
            <Text selectable style={commonStyles.muted}>{feedback || 'AI feedback will appear here.'}</Text>
          )}
        </View>

        <View style={{ flexDirection: 'row', gap: 8 }}>
          <Pressable accessibilityRole="button" onPress={restartQuiz} style={[commonStyles.primaryButton, { flex: 1 }]}>
            <Text style={commonStyles.primaryButtonText}>Retake Quiz</Text>
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  const questionNumber = currentIndex + 1;
  const totalQuestions = quiz.questions.length;
  if (!currentQuestion) {
    return (
      <View style={[commonStyles.fullScreen, commonStyles.emptyBox]}>
        <Text selectable style={commonStyles.emptyTitle}>Question not found</Text>
      </View>
    );
  }

  const activeQuestion = currentQuestion;
  const isCorrect = selectedAnswer !== null && selectedAnswer === resolveCorrectAnswerIndex(activeQuestion);

  return (
    <View style={commonStyles.fullScreen}>
      <View style={commonStyles.toolbar}>
        <View style={{ flex: 1 }}>
          <Text selectable style={commonStyles.toolbarTitle}>{quiz.name || 'Quiz'}</Text>
          <Text selectable style={commonStyles.muted}>
            {questionNumber} / {totalQuestions}
          </Text>
        </View>
      </View>

      <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
        <View style={commonStyles.progressTrack}>
          <View
            style={[
              commonStyles.progressFill,
              { width: `${Math.round((questionNumber / totalQuestions) * 100)}%` },
            ]}
          />
        </View>
      </View>

      <ScrollView contentInsetAdjustmentBehavior="automatic" contentContainerStyle={commonStyles.listContent}>
        <View style={commonStyles.card}>
          <Text selectable style={commonStyles.label}>Q{questionNumber}</Text>
          <Text selectable style={commonStyles.itemTitle}>
            {activeQuestion.question_text || activeQuestion.question || 'Question'}
          </Text>
          {activeQuestion.bloom_level ? (
            <Text selectable style={commonStyles.muted}>Bloom: {activeQuestion.bloom_level}</Text>
          ) : null}
        </View>

        <View style={{ gap: 8 }}>
          {(activeQuestion.choices || activeQuestion.options || []).map((choice, index) => {
            const selected = selectedAnswer === index;
            const correctIndex = resolveCorrectAnswerIndex(activeQuestion);
            const showCorrect = showResult && index === correctIndex;
            const showWrong = showResult && selected && selectedAnswer !== correctIndex;

            return (
              <Pressable
                key={`${currentIndex}-${index}`}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                disabled={showResult}
                onPress={() => handleAnswerSelect(index)}
                style={({ pressed }) => [
                  commonStyles.card,
                  { padding: 14 },
                  selected && !showResult && commonStyles.selectedCard,
                  showCorrect && { borderColor: colors.success, backgroundColor: '#f0fdf4' },
                  showWrong && { borderColor: colors.danger, backgroundColor: '#fef2f2' },
                  pressed && !showResult && commonStyles.pressed,
                ]}>
                <Text selectable style={commonStyles.bubbleText}>
                  {String.fromCharCode(65 + index)}. {choice}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {showResult && (
          <View style={[commonStyles.card, { backgroundColor: isCorrect ? '#f0fdf4' : '#fff7ed' }]}>
            <Text selectable style={[commonStyles.label, { color: isCorrect ? colors.success : colors.warning }]}>
              {isCorrect ? 'Correct' : 'Incorrect'}
            </Text>
            {activeQuestion.rationale ? (
              <Text selectable style={commonStyles.muted}>{activeQuestion.rationale}</Text>
            ) : null}
          </View>
        )}
      </ScrollView>

      <View style={[commonStyles.composer, { justifyContent: 'space-between', alignItems: 'center' }]}>
        <Pressable
          accessibilityRole="button"
          disabled={currentIndex === 0}
          onPress={handlePrevious}
          style={({ pressed }) => [
            commonStyles.secondaryButton,
            (pressed || currentIndex === 0) && commonStyles.pressed,
          ]}>
          <Text style={commonStyles.secondaryButtonText}>Previous</Text>
        </Pressable>

        {!showResult ? (
          <Pressable
            accessibilityRole="button"
            onPress={handleSubmitAnswer}
            style={({ pressed }) => [
              commonStyles.primaryButton,
              pressed && commonStyles.pressed,
            ]}>
            <Text style={commonStyles.primaryButtonText}>Submit Answer</Text>
          </Pressable>
        ) : (
          <Pressable
            accessibilityRole="button"
            disabled={submitting}
            onPress={handleNext}
            style={({ pressed }) => [
              commonStyles.primaryButton,
              (pressed || submitting) && commonStyles.pressed,
            ]}>
            <Text style={commonStyles.primaryButtonText}>
              {currentIndex === totalQuestions - 1 ? 'Finish Quiz' : 'Next Question'}
            </Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

function resolveCorrectAnswerIndex(question: QuizQuestion | null) {
  if (!question) {
    return null;
  }
  if (typeof question.correct_answer_index === 'number') {
    return question.correct_answer_index;
  }
  if (typeof question.answer_index === 'number') {
    return question.answer_index;
  }
  return null;
}

function calculateScore(questions: QuizQuestion[], userAnswers: (number | null)[]) {
  const correct = questions.reduce((total, question, index) => {
    const answer = userAnswers[index];
    const correctIndex = resolveCorrectAnswerIndex(question);
    return answer !== null && correctIndex === answer ? total + 1 : total;
  }, 0);
  const total = questions.length;
  return {
    correct,
    total,
    percentage: total > 0 ? Math.round((correct / total) * 100) : 0,
  };
}

function buildQuizFeedbackPayload(
  quiz: QuizDetail,
  answers: (number | null)[],
  score: { correct: number; total: number; percentage: number },
) {
  const questions = quiz.questions ?? [];
  const bloomStats: Record<string, { correct: number; total: number }> = {};

  questions.forEach((question, index) => {
    const level = question.bloom_level || 'general';
    if (!bloomStats[level]) {
      bloomStats[level] = { correct: 0, total: 0 };
    }
    bloomStats[level].total += 1;
    const correctIndex = resolveCorrectAnswerIndex(question);
    if (answers[index] !== null && correctIndex === answers[index]) {
      bloomStats[level].correct += 1;
    }
  });

  return {
    quiz_name: quiz.name || 'Quiz',
    score: score.correct,
    total_questions: score.total,
    percentage: score.percentage,
    bloom_summary: Object.entries(bloomStats).map(([level, stats]) => ({
      level,
      correct: stats.correct,
      total: stats.total,
      accuracy: stats.total ? Math.round((stats.correct / stats.total) * 100) : 0,
    })),
    questions: questions.map((question, index) => ({
      question: question.question_text || question.question,
      choices: question.choices || question.options,
      correct_answer_index: resolveCorrectAnswerIndex(question),
      user_answer_index: answers[index],
      bloom_level: question.bloom_level || 'general',
      rationale: question.rationale,
    })),
  };
}
