// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { createContext, useContext, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { authStore, AdminUser, AuthState } from "./authStore";
import { Permission } from "./permissions";
import { refreshAccessToken, parseApiError, getApiBaseUrl } from "@/api/client";

interface AuthContextValue {
  user: AdminUser | null;
  isAuthenticated: boolean;
  isBootstrapping: boolean;
  lockoutRemainingSeconds: number | null;
  login: (username: string, password: string, totpCode?: string) => Promise<void>;
  logout: () => Promise<void>;
  logoutEverywhere: () => Promise<void>;
  can: (permission: Permission) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<AuthState>(authStore.getState());
  const queryClient = useQueryClient();

  useEffect(() => {
    // Subscribe to store updates
    const unsubscribe = authStore.subscribe(setState);

    // Initial session bootstrap on mount (Hard Rule 3: recover session on refresh)
    refreshAccessToken()
      .then(() => {
        authStore.setBootstrapped();
      })
      .catch(() => {
        authStore.setBootstrapped();
      });

    return () => {
      unsubscribe();
    };
  }, []);

  const login = async (username: string, password: string, totpCode?: string): Promise<void> => {
    const baseUrl = getApiBaseUrl();
    const res = await fetch(`${baseUrl}/v1/admin/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "include",
      body: JSON.stringify({
        username,
        password,
        totp_code: totpCode || undefined,
      }),
    });

    if (!res.ok) {
      const err = await parseApiError(res);
      if (err.status === 423 && err.retryAfter) {
        authStore.setLockout(err.retryAfter);
      }
      throw err;
    }

    const data = await res.json();
    const user: AdminUser = {
      admin_id: data.admin_id,
      username: data.username,
      role: data.role,
      permissions: data.permissions || [],
    };

    authStore.setSession(data.access_token, user);
  };

  const logout = async (): Promise<void> => {
    try {
      const baseUrl = getApiBaseUrl();
      const token = authStore.getAccessToken();
      await fetch(`${baseUrl}/v1/admin/auth/logout`, {
        method: "POST",
        headers: {
          Authorization: token ? `Bearer ${token}` : "",
        },
        credentials: "include",
      });
    } catch {
      // Ignore network errors on logout
    } finally {
      // Clear session from volatile memory
      authStore.clearSession();
      // Hard Rule 3: Purge query cache so one admin's data never leaks to another
      queryClient.clear();
    }
  };

  const logoutEverywhere = async (): Promise<void> => {
    try {
      const baseUrl = getApiBaseUrl();
      const token = authStore.getAccessToken();
      await fetch(`${baseUrl}/v1/admin/auth/logout-everywhere`, {
        method: "POST",
        headers: {
          Authorization: token ? `Bearer ${token}` : "",
        },
        credentials: "include",
      });
    } finally {
      authStore.clearSession();
      queryClient.clear();
    }
  };

  const can = (permission: Permission): boolean => {
    return authStore.can(permission);
  };

  return (
    <AuthContext.Provider
      value={{
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        isBootstrapping: state.isBootstrapping,
        lockoutRemainingSeconds: state.lockoutRemainingSeconds,
        login,
        logout,
        logoutEverywhere,
        can,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useSession(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useSession must be used within an AuthProvider");
  }
  return ctx;
}
