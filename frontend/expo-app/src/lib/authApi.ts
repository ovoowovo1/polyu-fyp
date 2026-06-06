import {
  API_BASE_URL,
  CLIENT_PLATFORM,
  CLIENT_PLATFORM_HEADER,
  extractErrorMessage,
  getApiRefreshToken,
  requestJson,
  safeJsonParse,
} from '@/lib/apiClient';
import type { LoginResponse, LoginRole } from '@/lib/types';

export function login(email: string, password: string, role: LoginRole) {
  return requestJson<LoginResponse>('/auth/login', {
    method: 'POST',
    headers: { [CLIENT_PLATFORM_HEADER]: CLIENT_PLATFORM },
    body: JSON.stringify({ email, password, role }),
  });
}

export async function logoutSession(refreshToken: string = getApiRefreshToken() || '') {
  if (!refreshToken) {
    return;
  }

  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      [CLIENT_PLATFORM_HEADER]: CLIENT_PLATFORM,
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    const text = await response.text();
    const payload = text ? safeJsonParse(text) : null;
    throw new Error(extractErrorMessage(payload, response.status));
  }
}

export function verifyToken(token: string) {
  return fetch(`${API_BASE_URL}/auth/verify`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(async (response) => {
    const text = await response.text();
    const payload = text ? safeJsonParse(text) : null;
    if (!response.ok) {
      throw new Error(extractErrorMessage(payload, response.status));
    }
    return payload as { user?: LoginResponse['user'] };
  });
}
