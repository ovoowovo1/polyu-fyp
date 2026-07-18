import { canUploadSources } from '@/lib/sourceUploadAccess';

describe('canUploadSources', () => {
  it('allows teachers and hides upload controls from students', () => {
    expect(canUploadSources({ id: 'teacher-1', email: 'teacher@example.com', role: 'teacher' })).toBe(true);
    expect(canUploadSources({ id: 'student-1', email: 'student@example.com', role: 'student' })).toBe(false);
    expect(canUploadSources(null)).toBe(false);
  });
});
