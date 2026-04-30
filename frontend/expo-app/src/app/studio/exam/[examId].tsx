import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';

import { getExamById, getMyExamSubmissions, startExam, submitExam } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { colors, commonStyles } from '@/lib/styles';
import type { ExamAnswerPayload, ExamDetail, ExamQuestion, ExamSubmissionSummary } from '@/lib/types';

type ExamAnswerValue = number | string | null;

export default function ExamDetailScreen() {
  const { examId } = useLocalSearchParams<{ examId: string }>();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [submissions, setSubmissions] = useState<ExamSubmissionSummary[]>([]);
  const [submissionId, setSubmissionId] = useState<string | null>(null);
  const [answers, setAnswers] = useState<ExamAnswerValue[]>([]);
  const isTeacher = user?.role === 'teacher';

  useEffect(() => {
    if (!examId) {
      return;
    }

    async function load() {
      setLoading(true);
      try {
        const [examResult, mySubmissionResult] = await Promise.all([
          getExamById(examId, isTeacher),
          isTeacher ? Promise.resolve({ submissions: [], total: 0 }) : getMyExamSubmissions(examId),
        ]);
        const nextExam = examResult.exam;
        const nextSubmissions = mySubmissionResult.submissions ?? [];
        setExam(nextExam);
        setSubmissions(nextSubmissions);
        setAnswers(new Array(nextExam.questions?.length ?? 0).fill(null));
        const latestSubmission = nextSubmissions[0];
        setSubmissionId(latestSubmission?.submission_id || latestSubmission?.id || null);
      } catch (error) {
        Alert.alert('Exam load failed', error instanceof Error ? error.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [examId, isTeacher]);

  const readOnly = isTeacher || submissions.some((item) => item.status === 'submitted' || item.submitted_at);
  const activeSubmission = useMemo(
    () => submissions.find((item) => !item.submitted_at && item.status !== 'submitted') || null,
    [submissions],
  );

  const updateAnswer = (questionIndex: number, value: ExamAnswerValue) => {
    setAnswers((current) => {
      const next = [...current];
      next[questionIndex] = value;
      return next;
    });
  };

  const handleStartExam = async () => {
    if (!examId) {
      return;
    }
    setStarting(true);
    try {
      const started = await startExam(examId);
      setSubmissionId(started.submission_id);
    } catch (error) {
      Alert.alert('Start exam failed', error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setStarting(false);
    }
  };

  const handleSubmit = async () => {
    if (!submissionId || !exam?.questions?.length) {
      return;
    }

    const unanswered = answers.filter((answer) => answer === null || answer === '').length;
    if (unanswered > 0) {
      Alert.alert('Submit exam', `There are ${unanswered} unanswered questions. Submit anyway?`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Submit', onPress: () => void submitNow() },
      ]);
      return;
    }

    await submitNow();
  };

  const submitNow = async () => {
    if (!submissionId || !exam?.questions?.length) {
      return;
    }

    setSubmitting(true);
    try {
      const payloadAnswers: ExamAnswerPayload[] = exam.questions.map((question, index) => {
        const value = answers[index];
        const base = {
          question_id: question.question_id,
          exam_question_id: question.question_id,
        };
        if (resolveExamQuestionType(question) === 'multiple_choice' && (question.choices || []).length > 0) {
          return {
            ...base,
            answer_index: typeof value === 'number' ? value : null,
          };
        }
        return {
          ...base,
          answer_text: typeof value === 'string' ? value : '',
        };
      });

      await submitExam(submissionId, {
        answers: payloadAnswers,
        time_spent_seconds: null,
      });

      setSubmissions((current) => [
        {
          submission_id: submissionId,
          status: 'submitted',
          submitted_at: new Date().toISOString(),
        },
        ...current,
      ]);
    } catch (error) {
      Alert.alert('Submit exam failed', error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <View style={[commonStyles.fullScreen, commonStyles.emptyBox]}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (!exam) {
    return (
      <View style={[commonStyles.fullScreen, commonStyles.emptyBox]}>
        <Text selectable style={commonStyles.emptyTitle}>Exam not found</Text>
      </View>
    );
  }

  const canAnswer = !readOnly && (submissionId || activeSubmission);

  return (
    <View style={commonStyles.fullScreen}>
      <ScrollView contentInsetAdjustmentBehavior="automatic" contentContainerStyle={commonStyles.listContent}>
        <View style={commonStyles.card}>
          <Text selectable style={commonStyles.toolbarTitle}>{exam.title || 'Exam'}</Text>
          <Text selectable style={commonStyles.muted}>Questions: {exam.questions?.length ?? exam.num_questions ?? 0}</Text>
          <Text selectable style={commonStyles.muted}>
            Status: {exam.is_published ? 'Published' : 'Draft'}
          </Text>
          {typeof exam.duration_minutes === 'number' && (
            <Text selectable style={commonStyles.muted}>Duration: {exam.duration_minutes} minutes</Text>
          )}
          {!isTeacher && (
            <Text selectable style={commonStyles.muted}>
              Your submissions: {submissions.length}
            </Text>
          )}
        </View>

        {!isTeacher && !submissionId && !readOnly && (
          <View style={commonStyles.card}>
            <Text selectable style={commonStyles.label}>Ready to start?</Text>
            <Text selectable style={commonStyles.muted}>
              Start the exam to create a submission before answering the questions.
            </Text>
            <Pressable
              accessibilityRole="button"
              disabled={starting}
              onPress={() => void handleStartExam()}
              style={({ pressed }) => [
                commonStyles.primaryButton,
                (pressed || starting) && commonStyles.pressed,
              ]}>
              <Text style={commonStyles.primaryButtonText}>{starting ? 'Starting...' : 'Start Exam'}</Text>
            </Pressable>
          </View>
        )}

        {(exam.questions ?? []).map((question, index) => (
          <ExamQuestionBlock
            key={`${exam.id}-${index}`}
            index={index}
            question={question}
            readOnly={!canAnswer}
            showCorrectAnswer={isTeacher}
            value={answers[index] ?? null}
            onChange={updateAnswer}
          />
        ))}
      </ScrollView>

      {canAnswer && (
        <View style={commonStyles.composer}>
          <View style={{ flex: 1 }}>
            <Text selectable style={commonStyles.muted}>
              Answer according to the question type, then submit the exam.
            </Text>
          </View>
          <Pressable
            accessibilityRole="button"
            disabled={submitting}
            onPress={() => void handleSubmit()}
            style={({ pressed }) => [
              commonStyles.primaryButton,
              (pressed || submitting) && commonStyles.pressed,
            ]}>
            <Text style={commonStyles.primaryButtonText}>{submitting ? 'Submitting...' : 'Submit Exam'}</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

function ExamQuestionBlock({
  index,
  question,
  value,
  readOnly,
  showCorrectAnswer,
  onChange,
}: {
  index: number;
  question: ExamQuestion;
  value: ExamAnswerValue;
  readOnly: boolean;
  showCorrectAnswer: boolean;
  onChange: (index: number, value: ExamAnswerValue) => void;
}) {
  const questionType = resolveExamQuestionType(question);

  return (
    <View style={commonStyles.card}>
      <Text selectable style={commonStyles.label}>Q{index + 1}</Text>
      <Text selectable style={commonStyles.itemTitle}>{question.question_text || 'Question'}</Text>
      <Text selectable style={commonStyles.muted}>Type: {questionType}</Text>
      {typeof question.marks === 'number' && (
        <Text selectable style={commonStyles.muted}>Marks: {question.marks}</Text>
      )}
      {question.bloom_level ? <Text selectable style={commonStyles.muted}>Bloom: {question.bloom_level}</Text> : null}

      {questionType === 'multiple_choice' && (question.choices || []).length > 0 ? (
        <View style={{ gap: 8 }}>
          {(question.choices || []).map((choice, choiceIndex) => {
            const selected = value === choiceIndex;
            return (
              <Pressable
                key={`${index}-${choiceIndex}`}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                disabled={readOnly}
                onPress={() => onChange(index, choiceIndex)}
                style={({ pressed }) => [
                  commonStyles.card,
                  { padding: 12, gap: 6 },
                  selected && commonStyles.selectedCard,
                  (pressed || readOnly) && selected && commonStyles.pressed,
                ]}>
                <Text selectable style={commonStyles.bubbleText}>
                  {String.fromCharCode(65 + choiceIndex)}. {choice}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : (
        <TextInput
          editable={!readOnly}
          multiline={questionType !== 'short_answer'}
          onChangeText={(text) => onChange(index, text)}
          placeholder={questionType === 'calculation' ? 'Enter your calculation answer' : 'Enter your answer'}
          style={[
            commonStyles.input,
            {
              minHeight: questionType === 'essay' ? 140 : questionType === 'calculation' ? 100 : 52,
              textAlignVertical: 'top',
            },
          ]}
          value={typeof value === 'string' ? value : ''}
        />
      )}

      {showCorrectAnswer && typeof question.correct_answer_index === 'number' && (
        <Text selectable style={commonStyles.muted}>
          Answer: {String.fromCharCode(65 + question.correct_answer_index)}
        </Text>
      )}
      {showCorrectAnswer && questionType !== 'multiple_choice' && question.model_answer && (
        <Text selectable style={commonStyles.muted}>
          Reference answer: {question.model_answer}
        </Text>
      )}
    </View>
  );
}

function resolveExamQuestionType(question: ExamQuestion) {
  if (question.question_type) {
    return question.question_type;
  }
  return (question.choices || []).length > 0 ? 'multiple_choice' : 'short_answer';
}
