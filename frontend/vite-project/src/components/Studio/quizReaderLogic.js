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
