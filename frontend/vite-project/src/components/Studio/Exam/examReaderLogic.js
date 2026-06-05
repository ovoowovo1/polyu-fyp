export function examImageUrl(path, apiBaseUrl) {
    if (!path) return '';
    return path.startsWith('http://') || path.startsWith('https://') ? path : `${apiBaseUrl}${path}`;
}

export function createEmptyExamAnswers(questionCount) {
    return new Array(questionCount).fill(null);
}

export function restoreExamAnswer(userAnswers, index) {
    return userAnswers[index] ?? null;
}

export function nextExamIndex(currentIndex, questions) {
    return Math.min(currentIndex + 1, Math.max(questions.length - 1, 0));
}

export function previousExamIndex(currentIndex) {
    return Math.max(currentIndex - 1, 0);
}

export function questionInputMode(question = {}) {
    const hasChoices = (question.choices || []).length > 0;
    const marks = question.marks || 0;
    if (question.question_type === 'multiple_choice' && hasChoices) return 'multiple_choice';
    if (question.question_type === 'short_answer' || (question.question_type === 'multiple_choice' && marks <= 2)) {
        return 'short_answer';
    }
    if (question.question_type === 'essay' || question.question_type === 'long_answer' || marks > 2) {
        return 'essay';
    }
    return 'text';
}

export function buildExamSubmitPayload({ questions, userAnswers }) {
    return {
        answers: userAnswers.map((answer, index) => {
            const question = questions[index] || {};
            const base = {
                question_id: question.question_id,
                exam_question_id: question.exam_question_id,
            };
            if (questionInputMode(question) === 'multiple_choice') {
                return { ...base, answer_index: typeof answer === 'number' ? answer : null };
            }
            return { ...base, answer_text: typeof answer === 'string' ? answer : '' };
        }),
        time_spent_seconds: null,
    };
}
