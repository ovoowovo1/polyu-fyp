export function resolveExamListRole({ currentUser, storage }) {
    if (currentUser?.role) return currentUser.role;
    return storage?.getItem?.('role') || 'student';
}

export function formatExamCreatedAt(value, formatter) {
    return value ? formatter(value) : '-';
}

export function getExamStatusKey(isPublished) {
    return isPublished ? 'published' : 'unpublished';
}

export function getTeacherExamActionKeys(isPublished) {
    return [
        'view',
        isPublished ? 'unpublish' : 'publish',
        'submissions',
        'delete',
    ];
}

export function getStudentExamActionKeys(isPublished) {
    return [
        isPublished ? 'take' : 'notPublished',
        'myScore',
    ];
}
