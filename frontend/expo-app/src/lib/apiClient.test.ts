import {
  authHeaders,
  extractErrorMessage,
  getApiRefreshToken,
  getApiSessionToken,
  isUnauthorizedEvent,
  parseEventSourceData,
  requestFormData,
  requestJson,
  safeJsonParse,
  setApiTokens,
} from '@/lib/apiClient';

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

describe('apiClient', () => {
  beforeEach(() => {
    setApiTokens(null, null);
  });

  it('adds the current access token to ordinary JSON requests', async () => {
    setApiTokens('access-token', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({ classes: [] }));

    await requestJson('/classes/mine');

    const [, init] = fetchMock().mock.calls[0];
    expect((init?.headers as Headers).get('Authorization')).toBe('Bearer access-token');
  });

  it('refreshes once and retries a protected request after 401', async () => {
    setApiTokens('old-access', 'refresh-token');
    fetchMock().mockImplementation((input, init) => {
      const url = String(input);
      const auth = (init?.headers as Headers | undefined)?.get?.('Authorization');
      if (url.endsWith('/auth/refresh')) {
        expect((init?.headers as Record<string, string>)['X-Client-Platform']).toBe('expo-native');
        return Promise.resolve(jsonResponse({
          session_token: 'new-access',
          access_token: 'new-access',
          refresh_token: 'new-refresh',
          user: { email: 'teacher@example.com', role: 'teacher' },
        }));
      }
      if (auth === 'Bearer new-access') {
        return Promise.resolve(jsonResponse({ classes: [{ id: 'class-1' }] }));
      }
      return Promise.resolve(jsonResponse({ detail: 'expired' }, 401));
    });

    const result = await requestJson<{ classes: { id: string }[] }>('/classes/mine');

    expect(result.classes[0].id).toBe('class-1');
    expect(getApiSessionToken()).toBe('new-access');
    expect(getApiRefreshToken()).toBe('new-refresh');
    expect(fetchMock().mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'))).toHaveLength(1);
  });

  it('clears token state when refresh fails', async () => {
    setApiTokens('old-access', 'refresh-token');
    fetchMock().mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        return Promise.resolve(jsonResponse({ detail: 'invalid refresh' }, 401));
      }
      return Promise.resolve(jsonResponse({ detail: 'expired' }, 401));
    });

    await expect(requestJson('/classes/mine')).rejects.toThrow('invalid refresh');

    expect(getApiSessionToken()).toBeNull();
    expect(getApiRefreshToken()).toBeNull();
  });

  it('shares one refresh call across concurrent 401 requests', async () => {
    setApiTokens('old-access', 'refresh-token');
    fetchMock().mockImplementation((input, init) => {
      const url = String(input);
      const auth = (init?.headers as Headers | undefined)?.get?.('Authorization');
      if (url.endsWith('/auth/refresh')) {
        expect((init?.headers as Record<string, string>)['X-Client-Platform']).toBe('expo-native');
        return Promise.resolve(jsonResponse({
          session_token: 'new-access',
          access_token: 'new-access',
          refresh_token: 'new-refresh',
          user: { email: 'teacher@example.com', role: 'teacher' },
        }));
      }
      if (auth === 'Bearer new-access') {
        return Promise.resolve(jsonResponse({ ok: true }));
      }
      return Promise.resolve(jsonResponse({ detail: 'expired' }, 401));
    });

    await Promise.all([
      requestJson('/quiz/list?class_id=class-1'),
      requestJson('/exam/list?class_id=class-1'),
    ]);

    expect(fetchMock().mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'))).toHaveLength(1);
  });

  it('does not retry auth endpoints after 401', async () => {
    setApiTokens('old-access', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({ detail: 'bad login' }, 401));

    await expect(requestJson('/auth/login', { method: 'POST', body: '{}' })).rejects.toThrow('bad login');

    expect(fetchMock()).toHaveBeenCalledTimes(1);
  });

  it('refreshes and retries FormData requests after 401', async () => {
    setApiTokens('old-access', 'refresh-token');
    const formData = new FormData();
    formData.append('file_ids', 'file-1');
    fetchMock().mockImplementation((input, init) => {
      const url = String(input);
      const auth = (init?.headers as Headers | undefined)?.get?.('Authorization');
      if (url.endsWith('/auth/refresh')) {
        expect((init?.headers as Record<string, string>)['X-Client-Platform']).toBe('expo-native');
        return Promise.resolve(jsonResponse({
          session_token: 'new-access',
          access_token: 'new-access',
          refresh_token: 'new-refresh',
          user: { email: 'teacher@example.com', role: 'teacher' },
        }));
      }
      if (auth === 'Bearer new-access') {
        return Promise.resolve(jsonResponse({ quiz_id: 'quiz-1' }));
      }
      return Promise.resolve(jsonResponse({ detail: 'expired' }, 401));
    });

    await expect(requestFormData('/quiz/generate', formData)).resolves.toEqual({ quiz_id: 'quiz-1' });

    expect(fetchMock().mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'))).toHaveLength(1);
  });

  it('extracts consistent error messages from backend error payloads', async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ error: 'top level error' }, 400))
      .mockResolvedValueOnce(jsonResponse({ detail: { error: 'nested error' } }, 500))
      .mockResolvedValueOnce({
        ok: false,
        status: 502,
        text: jest.fn(() => Promise.resolve('plain upstream error')),
      } as unknown as Response);

    await expect(requestJson('/bad-one')).rejects.toThrow('top level error');
    await expect(requestJson('/bad-two')).rejects.toThrow('nested error');
    await expect(requestJson('/bad-three')).rejects.toThrow('plain upstream error');
  });

  it('covers auth header and parsing helpers', () => {
    expect(authHeaders({ Accept: 'text/event-stream' })).toEqual({ Accept: 'text/event-stream' });
    setApiTokens('access-token', 'refresh-token');
    expect(authHeaders({ Accept: 'text/event-stream' })).toEqual({
      Accept: 'text/event-stream',
      Authorization: 'Bearer access-token',
    });
    expect(isUnauthorizedEvent({ status: '401' })).toBe(true);
    expect(isUnauthorizedEvent({ message: 'Unauthorized request' })).toBe(true);
    expect(isUnauthorizedEvent({ status: 403 })).toBe(false);
    expect(parseEventSourceData({ data: '{"type":"progress","done":1}' })).toEqual({ type: 'progress', done: 1 });
    expect(parseEventSourceData({ data: 'not-json', type: 'message' })).toEqual({
      type: 'message',
      message: 'not-json',
    });
    expect(safeJsonParse('{"ok":true}')).toEqual({ ok: true });
    expect(safeJsonParse('bad-json')).toBe('bad-json');
    expect(extractErrorMessage(null, 503)).toBe('HTTP 503');
  });
});
