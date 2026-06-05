export function formatStudioDate(timestamp) {
    if (!timestamp) return '';

    const date = typeof timestamp === 'string'
        ? new Date(timestamp)
        : new Date(parseInt(timestamp, 10));

    if (Number.isNaN(date.getTime())) return '';

    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const year = date.getFullYear();
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${day}/${month}/${year} ${hours}:${minutes}`;
}

export function studioItemTimestamp(item) {
    if (!item?.created_at) return 0;
    if (typeof item.created_at === 'string') {
        const parsed = new Date(item.created_at).getTime();
        if (!Number.isNaN(parsed)) return parsed;
        const numeric = parseInt(item.created_at, 10);
        return Number.isNaN(numeric) ? 0 : numeric;
    }
    if (typeof item.created_at === 'number') {
        return item.created_at;
    }
    const parsed = parseInt(item.created_at, 10);
    return Number.isNaN(parsed) ? 0 : parsed;
}

export function mergeStudioItems(exams = [], quizzes = []) {
    return [
        ...(exams || []).map((exam) => ({ ...exam, _type: 'exam' })),
        ...(quizzes || []).map((quiz) => ({ ...quiz, _type: 'quiz' })),
    ].sort((a, b) => studioItemTimestamp(b) - studioItemTimestamp(a));
}

export function isCanceledRequest(error) {
    return error?.name === 'CanceledError' || error?.message === 'canceled';
}

export function examPdfFilename(examId, exams = []) {
    const exam = exams.find((item) => item.id === examId);
    return exam?.title ? `${exam.title}.pdf` : `exam_${examId}.pdf`;
}
