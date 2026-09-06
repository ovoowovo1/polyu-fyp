import test from 'node:test';
import assert from 'node:assert/strict';

import { login, register, getToken, logout } from '../api/auth.js';
import { createClass } from '../api/classes.js';
import { getExamList } from '../api/exam.js';
import { getAllQuizzes } from '../api/quiz.js';
import { clearDedupeCache } from '../utils/requestDeduper.js';
import { reingestPdf } from '../api/upload.js';
import { API_BASE_URL } from '../config.js';

const shouldRunIntegration = process.env.RUN_INTEGRATION_TESTS === '1';

test(
    'teacher can fetch Studio quiz and exam lists through frontend API helpers',
    { skip: shouldRunIntegration ? false : 'Set RUN_INTEGRATION_TESTS=1 to run backend contract tests.' },
    async () => {
        const storage = installLocalStorage();
        const suffix = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const email = `teacher-${suffix}@example.com`;
        const password = '12345678';

        try {
            const registered = await register(email, password, `Integration Teacher ${suffix}`, 'teacher');
            assert.equal(registered.user.email, email);
            assert.equal(registered.user.role, 'teacher');

            const loggedIn = await login(email, password, 'teacher');
            assert.ok(loggedIn.session_token);
            assert.equal(getToken(), loggedIn.session_token);

            const createdClass = await createClass(`Integration Class ${suffix}`);
            const classId = createdClass.class?.id;
            assert.ok(classId);

            clearDedupeCache(`quiz:list:${classId}`);
            const [quizResponse, examResponse] = await Promise.all([
                getAllQuizzes(classId),
                getExamList(classId),
            ]);

            assert.equal(quizResponse.status, 200);
            assert.equal(examResponse.status, 200);
            assert.ok(Array.isArray(quizResponse.data.quizzes));
            assert.ok(Array.isArray(examResponse.data.exams));

            // Unknown/out-of-scope documents must fail before any model request.
            const inaccessibleId = '00000000-0000-0000-0000-000000000001';
            const query = await fetch(`${API_BASE_URL}/api/query-stream`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: 'Explain atomicity', selectedFileIds: [inaccessibleId] }),
            });
            assert.equal(query.status, 403);
            await assert.rejects(
                reingestPdf(inaccessibleId, new Blob(['%PDF-fixture'], { type: 'application/pdf' }), `reingest-${suffix}`),
                (error) => error.response?.status === 403,
            );
        } finally {
            logout();
            storage.restore();
        }
    }
);

function installLocalStorage(initialValues = {}) {
    const originalLocalStorage = global.localStorage;
    const map = new Map(Object.entries(initialValues));

    global.localStorage = {
        getItem(key) {
            return map.has(key) ? map.get(key) : null;
        },
        setItem(key, value) {
            map.set(key, String(value));
        },
        removeItem(key) {
            map.delete(key);
        },
    };

    return {
        restore() {
            if (originalLocalStorage === undefined) {
                delete global.localStorage;
            } else {
                global.localStorage = originalLocalStorage;
            }
        },
    };
}
