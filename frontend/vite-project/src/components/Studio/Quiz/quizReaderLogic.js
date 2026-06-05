export const createEmptyAnswers = (questionCount) => new Array(questionCount).fill(null);

export const calculateQuizScore = (questions, userAnswers) => {
    const total = questions.length;
    const correct = questions.reduce(
        (count, question, index) => count + (userAnswers[index] === question.answer_index ? 1 : 0),
        0,
    );
    return {
        correct,
        total,
        percentage: total > 0 ? Math.round((correct / total) * 100) : 0,
    };
};

export const buildQuizFeedbackPayload = ({ quizName, questions, userAnswers, score }) => {
    const bloomStats = {};

    questions.forEach((question, index) => {
        const level = question.bloom_level || 'general';
        bloomStats[level] ||= { correct: 0, total: 0 };
        bloomStats[level].total += 1;
        if (userAnswers[index] === question.answer_index) {
            bloomStats[level].correct += 1;
        }
    });

    return {
        quiz_name: quizName,
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
            question: question.question,
            choices: question.choices,
            correct_answer_index: question.answer_index,
            user_answer_index: userAnswers[index],
            bloom_level: question.bloom_level || 'general',
            rationale: question.rationale,
        })),
    };
};

export const buildQuizAnswerPayload = (userAnswers) => userAnswers.map((answerIndex, questionIndex) => ({
    question_index: questionIndex,
    answer_index: answerIndex,
}));

export const storedAnswerAt = (userAnswers, index, fallbackAnswer = null) => {
    const storedAnswer = userAnswers?.[index];
    return storedAnswer !== null && storedAnswer !== undefined ? storedAnswer : fallbackAnswer;
};

export const nextQuizNavigationState = ({ currentIndex, questions, userAnswers }) => {
    if (currentIndex >= questions.length - 1) {
        return { isFinished: true };
    }
    const nextIndex = currentIndex + 1;
    const nextAnswer = userAnswers[nextIndex];
    return {
        currentIndex: nextIndex,
        selectedAnswer: nextAnswer,
        showResult: nextAnswer !== null,
        isFinished: false,
    };
};

export const previousQuizNavigationState = ({ currentIndex, userAnswers }) => {
    const previousIndex = Math.max(0, currentIndex - 1);
    const previousAnswer = userAnswers[previousIndex];
    return {
        currentIndex: previousIndex,
        selectedAnswer: previousAnswer,
        showResult: previousAnswer !== null,
    };
};

export const buildExplanationPrompt = ({ question, userAnswerIndex }) => {
    const toLetter = (index) => String.fromCharCode(65 + index);
    const userChoiceText = `${toLetter(userAnswerIndex)}. ${question.choices[userAnswerIndex]}`;
    const correctIndex = question.answer_index;
    const correctChoiceText = `${toLetter(correctIndex)}. ${question.choices[correctIndex]}`;
    const isCorrect = userAnswerIndex === correctIndex;

    return `When I took a quiz on this textbook, I saw this question:"${question.question}"\n\n` +
        `I chose the following answer:" ${userChoiceText}"\n\n` +
        (isCorrect
            ? 'That answer is correct.'
            : `That answer is incorrect. The correct answer is " ${correctChoiceText} "`) +
        '\n\nHelp me understand the reason why I got it wrong.';
};
