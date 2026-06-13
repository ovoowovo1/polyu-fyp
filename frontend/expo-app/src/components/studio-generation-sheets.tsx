import React from 'react';
import { Modal, Pressable, Switch, Text, TextInput, View } from 'react-native';

import { ModalSheet } from '@/components/modal-sheet';
import { QuestionCountInput } from '@/components/question-count-input';
import { SegmentRow } from '@/components/segment-row';
import { colors, commonStyles } from '@/lib/styles';
import {
  bloomOptions,
  difficultyOptions,
  QUESTION_LIMITS,
  type DifficultyOption,
  type ExamTotals,
} from '@/lib/studio-utils';

export function QuizGenerationSheet({
  visible,
  onClose,
  onSubmit,
  submitting,
  difficulty,
  onDifficultyChange,
  questionCount,
  onQuestionCountChange,
  bloomLevels,
  onToggleBloomLevel,
}: {
  visible: boolean;
  onClose: () => void;
  onSubmit: () => void;
  submitting: boolean;
  difficulty: DifficultyOption;
  onDifficultyChange: (value: DifficultyOption) => void;
  questionCount: string;
  onQuestionCountChange: (value: string) => void;
  bloomLevels: string[];
  onToggleBloomLevel: (value: string) => void;
}) {
  return (
    <Modal animationType="slide" transparent visible={visible} onRequestClose={onClose}>
      <ModalSheet title="Create Quiz" onCancel={onClose} onSubmit={onSubmit} submitting={submitting}>
        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Difficulty</Text>
          <SegmentRow
            options={difficultyOptions}
            selected={difficulty}
            onSelect={(value) => onDifficultyChange(value as DifficultyOption)}
          />
        </View>
        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Number of questions</Text>
          <TextInput
            keyboardType="number-pad"
            onChangeText={onQuestionCountChange}
            style={commonStyles.input}
            value={questionCount}
          />
        </View>
        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Bloom levels</Text>
          <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
            {bloomOptions.map((option) => (
              <ActionChip
                key={option}
                active={bloomLevels.includes(option)}
                label={option}
                onPress={() => onToggleBloomLevel(option)}
              />
            ))}
          </View>
        </View>
      </ModalSheet>
    </Modal>
  );
}

export function ExamGenerationSheet({
  visible,
  onClose,
  onSubmit,
  submitting,
  examName,
  onExamNameChange,
  topic,
  onTopicChange,
  totals,
  mcCount,
  onMcCountChange,
  shortAnswerCount,
  onShortAnswerCountChange,
  essayCount,
  onEssayCountChange,
  difficulty,
  onDifficultyChange,
  includeImages,
  onIncludeImagesChange,
  customPrompt,
  onCustomPromptChange,
}: {
  visible: boolean;
  onClose: () => void;
  onSubmit: () => void;
  submitting: boolean;
  examName: string;
  onExamNameChange: (value: string) => void;
  topic: string;
  onTopicChange: (value: string) => void;
  totals: ExamTotals;
  mcCount: string;
  onMcCountChange: (value: string) => void;
  shortAnswerCount: string;
  onShortAnswerCountChange: (value: string) => void;
  essayCount: string;
  onEssayCountChange: (value: string) => void;
  difficulty: DifficultyOption;
  onDifficultyChange: (value: DifficultyOption) => void;
  includeImages: boolean;
  onIncludeImagesChange: (value: boolean) => void;
  customPrompt: string;
  onCustomPromptChange: (value: string) => void;
}) {
  return (
    <Modal animationType="slide" transparent visible={visible} onRequestClose={onClose}>
      <ModalSheet
        title="Create Exam"
        onCancel={onClose}
        onSubmit={onSubmit}
        submitting={submitting}
        submitDisabled={totals.totalExamQuestions <= 0}>
        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Exam name</Text>
          <TextInput
            onChangeText={onExamNameChange}
            placeholder="Leave blank to auto-generate"
            style={commonStyles.input}
            value={examName}
          />
        </View>
        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Topic</Text>
          <TextInput onChangeText={onTopicChange} placeholder="Optional topic" style={commonStyles.input} value={topic} />
        </View>

        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Question type configuration</Text>
          <QuestionCountInput
            label="Multiple Choice"
            value={mcCount}
            max={QUESTION_LIMITS.multipleChoice.max}
            marks={QUESTION_LIMITS.multipleChoice.marks}
            onChange={onMcCountChange}
          />
          <QuestionCountInput
            label="Short Answer"
            value={shortAnswerCount}
            max={QUESTION_LIMITS.shortAnswer.max}
            marks={QUESTION_LIMITS.shortAnswer.marks}
            onChange={onShortAnswerCountChange}
          />
          <QuestionCountInput
            label="Essay"
            value={essayCount}
            max={QUESTION_LIMITS.essay.max}
            marks={QUESTION_LIMITS.essay.marks}
            onChange={onEssayCountChange}
          />
        </View>

        <View style={[commonStyles.card, { padding: 12, gap: 6 }]}>
          <Text style={commonStyles.muted}>Total questions: {totals.totalExamQuestions}</Text>
          <Text style={commonStyles.muted}>Total marks: {totals.totalExamMarks}</Text>
          {totals.totalExamQuestions === 0 ? (
            <Text style={[commonStyles.muted, { color: colors.danger }]}>
              Add at least one MCQ, short-answer, or essay question.
            </Text>
          ) : null}
        </View>

        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Difficulty</Text>
          <SegmentRow
            options={difficultyOptions}
            selected={difficulty}
            onSelect={(value) => onDifficultyChange(value as DifficultyOption)}
          />
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={commonStyles.label}>Include images</Text>
            <Text style={commonStyles.muted}>Include charts and visual materials when useful.</Text>
          </View>
          <Switch onValueChange={onIncludeImagesChange} value={includeImages} />
        </View>
        <View style={{ gap: 8 }}>
          <Text style={commonStyles.label}>Custom prompt</Text>
          <TextInput
            multiline
            maxLength={1000}
            onChangeText={onCustomPromptChange}
            placeholder="Optional instructions for exam generation"
            style={[commonStyles.input, { minHeight: 96, textAlignVertical: 'top' }]}
            value={customPrompt}
          />
          <Text style={commonStyles.muted}>{customPrompt.length}/1000</Text>
        </View>
      </ModalSheet>
    </Modal>
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
