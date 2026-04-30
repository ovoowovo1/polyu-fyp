import React, { createContext, PropsWithChildren, useCallback, useEffect, useMemo, useState } from 'react';

import { setApiSessionToken, verifyToken } from '@/lib/api';
import { deleteStoredValue, getStoredValue, setStoredValue } from '@/lib/storage';
import type { User } from '@/lib/types';

const TOKEN_KEY = 'session_token';
const USER_KEY = 'user';

type AuthContextValue = {
  bootstrapping: boolean;
  sessionToken: string | null;
  user: User | null;
  setSession: (token: string, user: User) => Promise<void>;
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
        const [storedToken, storedUser] = await Promise.all([
          getStoredValue(TOKEN_KEY),
          getStoredValue(USER_KEY),
        ]);

        if (!storedToken) {
          return;
        }

        setApiSessionToken(storedToken);
        let nextUser = storedUser ? JSON.parse(storedUser) as User : null;
        try {
          const verified = await verifyToken(storedToken);
          nextUser = verified.user || nextUser;
        } catch {
          await Promise.all([deleteStoredValue(TOKEN_KEY), deleteStoredValue(USER_KEY)]);
          setApiSessionToken(null);
          return;
        }

        if (mounted) {
          setSessionToken(storedToken);
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

  const setSession = useCallback(async (token: string, nextUser: User) => {
    await Promise.all([
      setStoredValue(TOKEN_KEY, token),
      setStoredValue(USER_KEY, JSON.stringify(nextUser)),
    ]);
    setApiSessionToken(token);
    setSessionToken(token);
    setUser(nextUser);
  }, []);

  const logout = useCallback(async () => {
    await Promise.all([deleteStoredValue(TOKEN_KEY), deleteStoredValue(USER_KEY)]);
    setApiSessionToken(null);
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

export function useAuth() {
  const context = React.use(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
