import { deleteStoredValue, setStoredValue } from '@/lib/storage';
import type { LoginResponse } from '@/lib/types';

export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || 'http://localhost:3000';
export const QUERY_TIMEOUT_MS = 120_000;
export const CLIENT_PLATFORM_HEADER = 'X-Client-Platform';
export const CLIENT_PLATFORM = 'expo-native';

const TOKEN_KEY = 'session_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';

let sessionToken: string | null = null;
let refreshTokenValue: string | null = null;
let refreshPromise: Promise<LoginResponse> | null = null;

export function setApiSessionToken(token: string | null) {
  sessionToken = token;
}

export function setApiRefreshToken(token: string | null) {
  refreshTokenValue = token;
}

export function setApiTokens(accessToken: string | null, refreshToken: string | null) {
  setApiSessionToken(accessToken);
  setApiRefreshToken(refreshToken);
}

export function getApiSessionToken() {
  return sessionToken;
}

export function getApiRefreshToken() {
  return refreshTokenValue;
}

export async function requestJson<T>(path: string, init: RequestInit = {}, retryOnUnauthorized = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (sessionToken) {
    headers.set('Authorization', `Bearer ${sessionToken}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  const text = await response.text();
  const payload = text ? safeJsonParse(text) : null;

  if (!response.ok) {
    if (response.status === 401 && retryOnUnauthorized && refreshTokenValue && !path.startsWith('/auth/')) {
      await refreshSession(refreshTokenValue);
      return requestJson<T>(path, init, false);
    }
    throw new Error(extractErrorMessage(payload, response.status));
  }

  return payload as T;
}

export async function requestFormData<T>(
  path: string,
  formData: FormData,
  retryOnUnauthorized = true,
): Promise<T> {
  const headers = new Headers();
  if (sessionToken) {
    headers.set('Authorization', `Bearer ${sessionToken}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body: formData,
  });
  const text = await response.text();
  const payload = text ? safeJsonParse(text) : null;

  if (!response.ok) {
    if (response.status === 401 && retryOnUnauthorized && refreshTokenValue) {
      await refreshSession(refreshTokenValue);
      return requestFormData<T>(path, formData, false);
    }
    throw new Error(extractErrorMessage(payload, response.status));
  }

  return payload as T;
}

export async function refreshSession(refreshToken: string = refreshTokenValue || '') {
  if (!refreshToken) {
    throw new Error('Refresh token missing.');
  }

  if (!refreshPromise) {
    refreshPromise = (async () => {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          [CLIENT_PLATFORM_HEADER]: CLIENT_PLATFORM,
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      const text = await response.text();
      const payload = text ? safeJsonParse(text) : null;

      if (!response.ok) {
        throw new Error(extractErrorMessage(payload, response.status));
      }

      const loginResponse = payload as LoginResponse;
      setApiTokens(loginResponse.access_token || loginResponse.session_token, loginResponse.refresh_token);
      await Promise.all([
        setStoredValue(TOKEN_KEY, loginResponse.access_token || loginResponse.session_token),
        setStoredValue(REFRESH_TOKEN_KEY, loginResponse.refresh_token),
        setStoredValue(USER_KEY, JSON.stringify(loginResponse.user)),
      ]);
      return loginResponse;
    })().catch(async (error) => {
      await clearStoredSession();
      throw error;
    }).finally(() => {
      refreshPromise = null;
    });
  }

  return refreshPromise;
}

export function authHeaders(base: Record<string, string> = {}) {
  return sessionToken ? { ...base, Authorization: `Bearer ${sessionToken}` } : base;
}

export function isUnauthorizedEvent(event: unknown) {
  if (!event || typeof event !== 'object') {
    return false;
  }
  const record = event as Record<string, unknown>;
  const status = record.status ?? record.statusCode;
  if (status === 401 || status === '401') {
    return true;
  }
  const message = String(record.message || record.type || '').toLowerCase();
  return message.includes('401') || message.includes('unauthorized');
}

export function parseEventSourceData(event: { data?: string | null; type?: string }): Record<string, unknown> {
  const data = event.data;
  if (!data) {
    return { type: event.type || 'message' };
  }

  const parsed = safeJsonParse(data);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    return parsed as Record<string, unknown>;
  }

  return {
    type: event.type || 'message',
    message: String(parsed),
  };
}

export function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export function extractErrorMessage(payload: unknown, status: number) {
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    const detail = record.detail;
    if (typeof record.error === 'string') return record.error;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && typeof (detail as Record<string, unknown>).error === 'string') {
      return String((detail as Record<string, unknown>).error);
    }
  }
  if (typeof payload === 'string' && payload.trim()) {
    return payload;
  }
  return `HTTP ${status}`;
}

async function clearStoredSession() {
  setApiTokens(null, null);
  await Promise.all([
    deleteStoredValue(TOKEN_KEY),
    deleteStoredValue(REFRESH_TOKEN_KEY),
    deleteStoredValue(USER_KEY),
  ]);
}
