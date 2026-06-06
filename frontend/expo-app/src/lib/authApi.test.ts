import { login, logoutSession, verifyToken } from '@/lib/authApi';
import { setApiTokens } from '@/lib/apiClient';

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: jest.fn(() => Promise.resolve(JSON.stringify(body))),
  } as unknown as Response;
}

function fetchMock() {
  return global.fetch as jest.MockedFunction<typeof fetch>;
}

describe('authApi', () => {
  beforeEach(() => {
    setApiTokens(null, null);
  });

  it('posts login credentials and returns the token response', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({
      session_token: 'access-token',
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      user: { email: 'teacher@example.com', role: 'teacher' },
    }));

    const result = await login('teacher@example.com', 'password', 'teacher');

    expect(result.refresh_token).toBe('refresh-token');
    const [, init] = fetchMock().mock.calls[0];
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      email: 'teacher@example.com',
      password: 'password',
      role: 'teacher',
    });
    expect((init?.headers as Headers).get('Content-Type')).toBe('application/json');
    expect((init?.headers as Headers).get('X-Client-Platform')).toBe('expo-native');
  });

  it('uses backend error messages for failed login', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ detail: { error: 'Login failed' } }, 401));

    await expect(login('teacher@example.com', 'bad', 'teacher')).rejects.toThrow('Login failed');
  });

  it('skips logout revoke when no refresh token is available', async () => {
    await logoutSession('');

    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it('revokes the refresh token during logout', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ ok: true }));

    await logoutSession('refresh-token');

    const [, init] = fetchMock().mock.calls[0];
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: 'refresh-token' });
    expect((init?.headers as Record<string, string>)['X-Client-Platform']).toBe('expo-native');
  });

  it('throws backend errors when logout revoke fails', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ detail: 'Token already revoked' }, 401));

    await expect(logoutSession('refresh-token')).rejects.toThrow('Token already revoked');
  });

  it('verifies an access token with the bearer header', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({
      user: { email: 'student@example.com', role: 'student' },
    }));

    const result = await verifyToken('access-token');

    expect(result.user?.email).toBe('student@example.com');
    const [, init] = fetchMock().mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer access-token');
  });

  it('throws backend errors when verify fails', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token' }, 401));

    await expect(verifyToken('bad-token')).rejects.toThrow('Invalid token');
  });
});
