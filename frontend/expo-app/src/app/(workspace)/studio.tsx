import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { ModalSheet } from '@/components/modal-sheet';
import { QuestionCountInput } from '@/components/question-count-input';
import { SegmentRow } from '@/components/segment-row';
import { StudioItemCard } from '@/components/studio-item-card';
import { generateExam, generateQuiz, listExams, listQuizzes } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { useDocumentWorkspace } from '@/lib/document-workspace-context';
import { colors, commonStyles } from '@/lib/styles';
import {
  clampQuestionCount,
  QUESTION_LIMITS,
  type StudioItem,
} from '@/lib/studio-utils';
import type { ExamSummary, QuizSummary } from '@/lib/types';

const difficultyOptions = ['easy', 'medium', 'difficult'] as const;
const bloomOptions = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'] as const;

export default function StudioScreen() {
  const { user } = useAuth();
  const { currentClass, selectedIds } = useDocumentWorkspace();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [quizModalOpen, setQuizModalOpen] = useState(false);
  const [examModalOpen, setExamModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [quizDifficulty, setQuizDifficulty] = useState<(typeof difficultyOptions)[number]>('medium');
  const [quizQuestions, setQuizQuestions] = useState('5');
  const [quizBloomLevels, setQuizBloomLevels] = useState<string[]>(['understand']);
  const [examDifficulty, setExamDifficulty] = useState<(typeof difficultyOptions)[number]>('medium');
  const [mcCount, setMcCount] = useState('5');
  const [shortAnswerCount, setShortAnswerCount] = useState('3');
  const [essayCount, setEssayCount] = useState('2');
  const [examTopic, setExamTopic] = useState('');
  const [examName, setExamName] = useState('');
  const [customPrompt, setCustomPrompt] = useState('');
  const [includeImages, setIncludeImages] = useState(true);

  const isTeacher = user?.role === 'teacher';

  const loadStudio = useCallback(async (showRefresh = false) => {
    if (!currentClass?.id) {
      setQuizzes([]);
      setExams([]);
      setLoading(false);
      setRefreshing(false);
      return;
    }

    if (showRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const [quizResult, examResult] = await Promise.all([
        listQuizzes(String(currentClass.id)),
        listExams(String(currentClass.id)),
      ]);
      setQuizzes(quizResult.quizzes ?? []);
      setExams(examResult.exams ?? []);
    } catch (error) {
      Alert.alert('Studio load failed', error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [currentClass?.id]);

  useEffect(() => {
    void loadStudio();
  }, [loadStudio]);

  const items = useMemo<StudioItem[]>(() => {
    const quizItems = quizzes.map((quiz) => ({
      id: quiz.id,
      createdAt: Date.parse(quiz.created_at || '') || 0,
      type: 'quiz' as const,
      title: quiz.name || 'Untitled quiz',
      raw: quiz,
    }));
    const examItems = exams.map((exam) => ({
      id: exam.id,
      createdAt: Date.parse(exam.created_at || '') || 0,
      type: 'exam' as const,
      title: exam.title || 'Untitled exam',
      raw: exam,
    }));
    return [...examItems, ...quizItems].sort((a, b) => b.createdAt - a.createdAt);
  }, [exams, quizzes]);

  const examTypeCounts = useMemo(() => ({
    multipleChoice: clampQuestionCount(mcCount, QUESTION_LIMITS.multipleChoice.max),
    shortAnswer: clampQuestionCount(shortAnswerCount, QUESTION_LIMITS.shortAnswer.max),
    essay: clampQuestionCount(essayCount, QUESTION_LIMITS.essay.max),
  }), [essayCount, mcCount, shortAnswerCount]);

  const totalExamQuestions = examTypeCounts.multipleChoice + examTypeCounts.shortAnswer + examTypeCounts.essay;
  const totalExamMarks = (
    examTypeCounts.multipleChoice * QUESTION_LIMITS.multipleChoice.marks +
    examTypeCounts.shortAnswer * QUESTION_LIMITS.shortAnswer.marks +
    examTypeCounts.essay * QUESTION_LIMITS.essay.marks
  );

  const openStudioItem = (item: StudioItem) => {
    if (item.type === 'quiz') {
      router.push({
        pathname: '/studio/quiz/[quizId]',
        params: { quizId: item.id },
      });
      return;
    }
    router.push({
      pathname: '/studio/exam/[examId]',
      params: { examId: item.id },
    });
  };

  const toggleBloomLevel = (value: string) => {
    setQuizBloomLevels((current) => (
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
    ));
  };

  const submitQuizGeneration = async () => {
    if (selectedIds.length === 0) {
      Alert.alert('Select source documents first', 'Go to Source and select at least one document.');
      return;
    }

    setSubmitting(true);
    try {
      await generateQuiz({
        fileIds: selectedIds,
        difficulty: quizDifficulty,
        numQuestions: Math.max(1, Number(quizQuestions) || 5),
        bloomLevels: quizBloomLevels.length > 0 ? quizBloomLevels : ['understand'],
      });
      setQuizModalOpen(false);
      await loadStudio();
      Alert.alert('Quiz created', 'The new quiz is now available in Studio.');
    } catch (error) {
      Alert.alert('Quiz creation failed', error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  const submitExamGeneration = async () => {
    if (selectedIds.length === 0) {
      Alert.alert('Select source documents first', 'Go to Source and select at least one document.');
      return;
    }

    if (totalExamQuestions <= 0) {
      Alert.alert('Select question types', 'Add at least one MCQ, short-answer, or essay question.');
      return;
    }

    setSubmitting(true);
    try {
      await generateExam({
        fileIds: selectedIds,
        topic: examTopic.trim() || undefined,
        difficulty: examDifficulty,
        numQuestions: totalExamQuestions,
        questionTypes: {
          multiple_choice: examTypeCounts.multipleChoice,
          short_answer: examTypeCounts.shortAnswer,
          essay: examTypeCounts.essay,
        },
        examName: examName.trim() || undefined,
        includeImages,
        customPrompt: customPrompt.trim() || undefined,
      });
      setExamModalOpen(false);
      await loadStudio();
      Alert.alert('Exam created', 'The new exam is now available in Studio.');
    } catch (error) {
      Alert.alert('Exam creation failed', error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={commonStyles.fullScreen}>
      <FlatList
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={commonStyles.listContent}
        data={items}
        keyExtractor={(item) => `${item.type}-${item.id}`}
        ListHeaderComponent={(
          <View style={{ gap: 12 }}>
            <View style={commonStyles.card}>
              <Text selectable style={commonStyles.toolbarTitle}>
                {currentClass?.name || 'Studio'}
              </Text>
              <Text selectable style={commonStyles.muted}>
                {isTeacher
                  ? 'Manage quizzes and exams for this class.'
                  : 'Open quizzes and exams for this class.'}
              </Text>
              <Text selectable style={commonStyles.muted}>
                Selected documents: {selectedIds.length}
              </Text>
            </View>

            {isTeacher && (
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <ActionButton
                  disabled={selectedIds.length === 0}
                  label="Create Quiz"
                  onPress={() => setQuizModalOpen(true)}
                />
                <ActionButton
                  disabled={selectedIds.length === 0}
                  label="Create Exam"
                  onPress={() => setExamModalOpen(true)}
                />
              </View>
            )}

            {loading && <ActivityIndicator color={colors.primary} />}
          </View>
        )}
        ListEmptyComponent={!loading ? (
          <View style={commonStyles.emptyBox}>
            <Text selectable style={commonStyles.emptyTitle}>No studio records</Text>
            <Text selectable style={commonStyles.muted}>
              Quizzes and exams for this class will appear here.
            </Text>
          </View>
        ) : null}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadStudio(true)} />}
        renderItem={({ item }) => (
          <StudioItemCard item={item} onPress={() => openStudioItem(item)} />
        )}
      />

      <Modal animationType="slide" transparent visible={quizModalOpen} onRequestClose={() => setQuizModalOpen(false)}>
        <ModalSheet
          title="Create Quiz"
          onCancel={() => setQuizModalOpen(false)}
          onSubmit={submitQuizGeneration}
          submitting={submitting}>
          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Difficulty</Text>
            <SegmentRow options={difficultyOptions} selected={quizDifficulty} onSelect={(value) => setQuizDifficulty(value as typeof difficultyOptions[number])} />
          </View>
          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Number of questions</Text>
            <TextInput keyboardType="number-pad" onChangeText={setQuizQuestions} style={commonStyles.input} value={quizQuestions} />
          </View>
          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Bloom levels</Text>
            <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
              {bloomOptions.map((option) => {
                const active = quizBloomLevels.includes(option);
                return (
                  <ActionChip
                    key={option}
                    active={active}
                    label={option}
                    onPress={() => toggleBloomLevel(option)}
                  />
                );
              })}
            </View>
          </View>
        </ModalSheet>
      </Modal>

      <Modal animationType="slide" transparent visible={examModalOpen} onRequestClose={() => setExamModalOpen(false)}>
        <ModalSheet
          title="Create Exam"
          onCancel={() => setExamModalOpen(false)}
          onSubmit={submitExamGeneration}
          submitting={submitting}
          submitDisabled={totalExamQuestions <= 0}>
          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Exam name</Text>
            <TextInput
              onChangeText={setExamName}
              placeholder="Leave blank to auto-generate"
              style={commonStyles.input}
              value={examName}
            />
          </View>
          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Topic</Text>
            <TextInput onChangeText={setExamTopic} placeholder="Optional topic" style={commonStyles.input} value={examTopic} />
          </View>

          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Question type configuration</Text>
            <QuestionCountInput
              label="Multiple Choice"
              value={mcCount}
              max={QUESTION_LIMITS.multipleChoice.max}
              marks={QUESTION_LIMITS.multipleChoice.marks}
              onChange={setMcCount}
            />
            <QuestionCountInput
              label="Short Answer"
              value={shortAnswerCount}
              max={QUESTION_LIMITS.shortAnswer.max}
              marks={QUESTION_LIMITS.shortAnswer.marks}
              onChange={setShortAnswerCount}
            />
            <QuestionCountInput
              label="Essay"
              value={essayCount}
              max={QUESTION_LIMITS.essay.max}
              marks={QUESTION_LIMITS.essay.marks}
              onChange={setEssayCount}
            />
          </View>

          <View style={[commonStyles.card, { padding: 12, gap: 6 }]}>
            <Text style={commonStyles.muted}>Total questions: {totalExamQuestions}</Text>
            <Text style={commonStyles.muted}>Total marks: {totalExamMarks}</Text>
            {totalExamQuestions === 0 ? (
              <Text style={[commonStyles.muted, { color: colors.danger }]}>
                Add at least one MCQ, short-answer, or essay question.
              </Text>
            ) : null}
          </View>

          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Difficulty</Text>
            <SegmentRow options={difficultyOptions} selected={examDifficulty} onSelect={(value) => setExamDifficulty(value as typeof difficultyOptions[number])} />
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={commonStyles.label}>Include images</Text>
              <Text style={commonStyles.muted}>Include charts and visual materials when useful.</Text>
            </View>
            <Switch onValueChange={setIncludeImages} value={includeImages} />
          </View>
          <View style={{ gap: 8 }}>
            <Text style={commonStyles.label}>Custom prompt</Text>
            <TextInput
              multiline
              maxLength={1000}
              onChangeText={setCustomPrompt}
              placeholder="Optional instructions for exam generation"
              style={[commonStyles.input, { minHeight: 96, textAlignVertical: 'top' }]}
              value={customPrompt}
            />
            <Text style={commonStyles.muted}>{customPrompt.length}/1000</Text>
          </View>
        </ModalSheet>
      </Modal>
    </View>
  );
}

function ActionButton({
  disabled,
  label,
  onPress,
}: {
  disabled: boolean;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        commonStyles.primaryButton,
        { flex: 1 },
        (pressed || disabled) && commonStyles.pressed,
      ]}>
      <Text style={commonStyles.primaryButtonText}>{label}</Text>
    </Pressable>
  );
}

function ActionChip({
  active,
  label,
  onPress,
}: {
  active: boolean;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={[
        commonStyles.compactButton,
        active && { backgroundColor: colors.primary },
      ]}>
      <Text style={[commonStyles.compactButtonText, active && { color: '#fff' }]}>{label}</Text>
    </Pressable>
  );
}
