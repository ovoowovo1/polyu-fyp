import React, { createContext, PropsWithChildren, useCallback, useEffect, useMemo, useState } from 'react';

import { logoutSession, refreshSession, setApiTokens, verifyToken } from '@/lib/api';
import { deleteStoredValue, getStoredValue, setStoredValue } from '@/lib/storage';
import type { User } from '@/lib/types';

const TOKEN_KEY = 'session_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';

type AuthContextValue = {
  bootstrapping: boolean;
  sessionToken: string | null;
  user: User | null;
  setSession: (token: string, refreshToken: string, user: User) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [bootstrapping, setBootstrapping] = useState(true);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let mounted = true;

    async function bootstrap() {
      try {
        const [storedToken, storedRefreshToken, storedUser] = await Promise.all([
          getStoredValue(TOKEN_KEY),
          getStoredValue(REFRESH_TOKEN_KEY),
          getStoredValue(USER_KEY),
        ]);

        if (!storedToken && !storedRefreshToken) {
          return;
        }

        setApiTokens(storedToken, storedRefreshToken);
        let nextToken = storedToken;
        let nextUser = storedUser ? JSON.parse(storedUser) as User : null;
        try {
          if (storedToken) {
            const verified = await verifyToken(storedToken);
            nextUser = verified.user || nextUser;
          } else if (storedRefreshToken) {
            const refreshed = await refreshSession(storedRefreshToken);
            await persistSession(refreshed.session_token, refreshed.refresh_token, refreshed.user);
            nextToken = refreshed.session_token;
            nextUser = refreshed.user || nextUser;
          }
        } catch {
          if (!storedRefreshToken) {
            await clearSession();
            return;
          }
          try {
            const refreshed = await refreshSession(storedRefreshToken);
            await persistSession(refreshed.session_token, refreshed.refresh_token, refreshed.user);
            nextToken = refreshed.session_token;
            nextUser = refreshed.user || nextUser;
          } catch {
            await clearSession();
            return;
          }
        }

        if (mounted) {
          setSessionToken(nextToken);
          setUser(nextUser);
        }
      } finally {
        if (mounted) {
          setBootstrapping(false);
        }
      }
    }

    void bootstrap();
    return () => {
      mounted = false;
    };
  }, []);

  const setSession = useCallback(async (token: string, refreshToken: string, nextUser: User) => {
    await persistSession(token, refreshToken, nextUser);
    setSessionToken(token);
    setUser(nextUser);
  }, []);

  const logout = useCallback(async () => {
    const storedRefreshToken = await getStoredValue(REFRESH_TOKEN_KEY);
    if (storedRefreshToken) {
      try {
        await logoutSession(storedRefreshToken);
      } catch {
        // Local logout should still succeed even if the server revoke call fails.
      }
    }
    await clearSession();
    setSessionToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({
    bootstrapping,
    sessionToken,
    user,
    setSession,
    logout,
  }), [bootstrapping, logout, sessionToken, setSession, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

async function persistSession(token: string, refreshToken: string, user: User) {
  await Promise.all([
    setStoredValue(TOKEN_KEY, token),
    setStoredValue(REFRESH_TOKEN_KEY, refreshToken),
    setStoredValue(USER_KEY, JSON.stringify(user)),
  ]);
  setApiTokens(token, refreshToken);
}

async function clearSession() {
  await Promise.all([
    deleteStoredValue(TOKEN_KEY),
    deleteStoredValue(REFRESH_TOKEN_KEY),
    deleteStoredValue(USER_KEY),
  ]);
  setApiTokens(null, null);
}

export function useAuth() {
  const context = React.use(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
