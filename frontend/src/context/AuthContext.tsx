import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api, AuthUser, hasRole, Role, setMfaRequiredHandler, setUnauthorizedHandler } from '../services/api';

/** Thrown by login() when the password was right and a TOTP / recovery code is needed. */
export class MfaRequiredError extends Error {}

interface AuthContextType {
  user: AuthUser | null;
  checking: boolean;
  login: (username: string, password: string, otp?: string) => Promise<void>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;
  refresh: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    setMfaRequiredHandler(() => refresh());
    refresh().finally(() => setChecking(false));
    return () => {
      setUnauthorizedHandler(null);
      setMfaRequiredHandler(null);
    };
  }, [refresh]);

  const login = useCallback(async (username: string, password: string, otp?: string) => {
    try {
      setUser(await api.login(username, password, otp));
    } catch (e: any) {
      if (e.response?.status === 401 && e.response?.data?.detail === 'mfa_required') {
        throw new MfaRequiredError();
      }
      throw e;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
    }
  }, []);

  const logoutAll = useCallback(async () => {
    try {
      await api.logoutAll();
    } finally {
      setUser(null);
    }
  }, []);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    await api.changePassword(currentPassword, newPassword);
  }, []);

  return (
    <AuthContext.Provider value={{ user, checking, login, logout, logoutAll, refresh, changePassword }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};

/** `can('operator')` → true if the signed-in user has at least that role. UI hint only; the backend enforces. */
export const useCan = () => {
  const { user } = useAuth();
  return (needed: Role) => hasRole(user, needed);
};
