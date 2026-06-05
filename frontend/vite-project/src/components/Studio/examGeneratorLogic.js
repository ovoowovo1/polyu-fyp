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
