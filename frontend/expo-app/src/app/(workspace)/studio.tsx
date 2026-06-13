import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { ExamGenerationSheet, QuizGenerationSheet } from '@/components/studio-generation-sheets';
import { StudioItemCard } from '@/components/studio-item-card';
import { generateExam, generateQuiz, listExams, listQuizzes } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { useDocumentWorkspace } from '@/lib/document-workspace-context';
import { colors, commonStyles } from '@/lib/styles';
import {
  buildExamGenerationPayload,
  buildQuizGenerationPayload,
  buildStudioItems,
  calculateExamTotals,
  calculateExamTypeCounts,
  type DifficultyOption,
  type StudioItem,
} from '@/lib/studio-utils';
import type { ExamSummary, QuizSummary } from '@/lib/types';

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
  const [quizDifficulty, setQuizDifficulty] = useState<DifficultyOption>('medium');
  const [quizQuestions, setQuizQuestions] = useState('5');
  const [quizBloomLevels, setQuizBloomLevels] = useState<string[]>(['understand']);
  const [examDifficulty, setExamDifficulty] = useState<DifficultyOption>('medium');
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

  const items = useMemo<StudioItem[]>(() => buildStudioItems(quizzes, exams), [exams, quizzes]);

  const examTypeCounts = useMemo(
    () => calculateExamTypeCounts({ mcCount, shortAnswerCount, essayCount }),
    [essayCount, mcCount, shortAnswerCount],
  );
  const examTotals = useMemo(() => calculateExamTotals(examTypeCounts), [examTypeCounts]);

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
      await generateQuiz(buildQuizGenerationPayload({
        selectedIds,
        difficulty: quizDifficulty,
        quizQuestions,
        bloomLevels: quizBloomLevels,
      }));
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

    if (examTotals.totalExamQuestions <= 0) {
      Alert.alert('Select question types', 'Add at least one MCQ, short-answer, or essay question.');
      return;
    }

    setSubmitting(true);
    try {
      await generateExam(buildExamGenerationPayload({
        selectedIds,
        topic: examTopic,
        difficulty: examDifficulty,
        totalQuestions: examTotals.totalExamQuestions,
        typeCounts: examTypeCounts,
        examName,
        includeImages,
        customPrompt,
      }));
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

      <QuizGenerationSheet
        visible={quizModalOpen}
        onClose={() => setQuizModalOpen(false)}
        onSubmit={submitQuizGeneration}
        submitting={submitting}
        difficulty={quizDifficulty}
        onDifficultyChange={setQuizDifficulty}
        questionCount={quizQuestions}
        onQuestionCountChange={setQuizQuestions}
        bloomLevels={quizBloomLevels}
        onToggleBloomLevel={toggleBloomLevel}
      />

      <ExamGenerationSheet
        visible={examModalOpen}
        onClose={() => setExamModalOpen(false)}
        onSubmit={submitExamGeneration}
        submitting={submitting}
        examName={examName}
        onExamNameChange={setExamName}
        topic={examTopic}
        onTopicChange={setExamTopic}
        totals={examTotals}
        mcCount={mcCount}
        onMcCountChange={setMcCount}
        shortAnswerCount={shortAnswerCount}
        onShortAnswerCountChange={setShortAnswerCount}
        essayCount={essayCount}
        onEssayCountChange={setEssayCount}
        difficulty={examDifficulty}
        onDifficultyChange={setExamDifficulty}
        includeImages={includeImages}
        onIncludeImagesChange={setIncludeImages}
        customPrompt={customPrompt}
        onCustomPromptChange={setCustomPrompt}
      />
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
