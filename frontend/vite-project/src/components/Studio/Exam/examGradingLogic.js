export function mergeAiGradingResults(answers = [], gradedAnswers = []) {
    const aiGradedIds = new Set();
    const mergedAnswers = answers.map((answer) => {
        const aiResult = gradedAnswers.find(
            (result) => result.answer_id === answer.id || result.exam_question_id === answer.exam_question_id,
        );
        if (!aiResult?.ai_graded) return answer;
        aiGradedIds.add(answer.id);
        return {
            ...answer,
            marks_earned: aiResult.marks_earned,
            teacher_feedback: aiResult.teacher_feedback,
        };
    });
    return { answers: mergedAnswers, aiGradedIds };
}

export function buildManualGradePayload({ answers = [], teacherComment = '' }) {
    return {
        answers_grades: answers.map((answer) => ({
            answer_id: answer.id,
            exam_question_id: answer.exam_question_id,
            marks_earned: answer.marks_earned ?? 0,
            teacher_feedback: answer.teacher_feedback,
        })),
        teacher_comment: teacherComment,
    };
}
