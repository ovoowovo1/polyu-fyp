export function buildExamGenerationPayload({
    selectedFileIds,
    topic,
    difficulty,
    mcCount,
    shortAnswerCount,
    essayCount,
    examName,
    includeImages,
    customPrompt,
}) {
    return {
        file_ids: selectedFileIds,
        topic: topic || undefined,
        difficulty,
        num_questions: mcCount + shortAnswerCount + essayCount,
        question_types: {
            multiple_choice: mcCount,
            short_answer: shortAnswerCount,
            essay: essayCount,
        },
        exam_name: examName || undefined,
        include_images: includeImages,
        custom_prompt: customPrompt || undefined,
    };
}

export function getExamProgressStage(progress, translate) {
    return [
        { p: 20, s: translate('exam.generator.analyzing') },
        { p: 40, s: translate('exam.generator.generating') },
        { p: 60, s: translate('exam.generator.generatingCharts') },
        { p: 75, s: translate('exam.generator.reviewing') },
        { p: 85, s: translate('exam.generator.generatingPdf') },
    ].find((stage) => stage.p > progress);
}

export function examQuestionTypeLabel(questionType, translate) {
    if (questionType === 'multiple_choice') return translate('exam.generator.questionTypeMultipleChoice');
    if (questionType === 'short_answer') return translate('exam.generator.questionTypeShortAnswer');
    return translate('exam.generator.questionTypeEssay');
}

export function examQuestionTypeColor(questionType) {
    if (questionType === 'multiple_choice') return 'blue';
    if (questionType === 'short_answer') return 'orange';
    return 'purple';
}

export function examGenerationTotals({ mcCount, shortAnswerCount, essayCount }) {
    return {
        questions: mcCount + shortAnswerCount + essayCount,
        marks: mcCount + shortAnswerCount * 2 + essayCount * 5,
    };
}

export function examResultQuestionPreview(questions = [], limit = 5) {
    return {
        questions: questions.slice(0, limit),
        remainingCount: Math.max(0, questions.length - limit),
    };
}
