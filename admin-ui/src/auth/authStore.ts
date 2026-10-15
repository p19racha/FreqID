// Copyright 2026 FreqID Authors. Apache-2.0 License.
/**
 * authStore.ts: In-memory authentication state store (Hard Rule 3).
 * Access tokens and user identity are kept strictly in volatile memory.
 * No tokens or secrets are ever persisted to localStorage or sessionStorage.
 */

import { AdminRole, Permission, hasPermission } from "./permissions";

export interface AdminUser {
  admin_id: string;
  username: string;
  role: AdminRole;
  permissions: Permission[];
}

export interface AuthState {
  accessToken: string | null;
  user: AdminUser | null;
  isAuthenticated: boolean;
  isBootstrapping: boolean;
  lockoutRemainingSeconds: number | null;
}

type Subscriber = (state: AuthState) => void;

class AuthStore {
  private state: AuthState = {
    accessToken: null,
    user: null,
    isAuthenticated: false,
    isBootstrapping: true,
    lockoutRemainingSeconds: null,
  };

  private subscribers: Set<Subscriber> = new Set();

  getState(): AuthState {
    return this.state;
  }

  getAccessToken(): string | null {
    return this.state.accessToken;
  }

  getUser(): AdminUser | null {
    return this.state.user;
  }

  isAuthenticated(): boolean {
    return this.state.isAuthenticated;
  }

  can(permission: Permission): boolean {
    if (!this.state.user) return false;
    return hasPermission(this.state.user.role, permission);
  }

  setSession(token: string, user: AdminUser): void {
    this.state = {
      accessToken: token,
      user,
      isAuthenticated: true,
      isBootstrapping: false,
      lockoutRemainingSeconds: null,
    };
    this.notify();
  }

  clearSession(): void {
    this.state = {
      accessToken: null,
      user: null,
      isAuthenticated: false,
      isBootstrapping: false,
      lockoutRemainingSeconds: null,
    };
    this.notify();
  }

  setBootstrapped(): void {
    if (this.state.isBootstrapping) {
      this.state = {
        ...this.state,
        isBootstrapping: false,
      };
      this.notify();
    }
  }

  setLockout(seconds: number): void {
    this.state = {
      ...this.state,
      lockoutRemainingSeconds: seconds,
    };
    this.notify();
  }

  subscribe(fn: Subscriber): () => void {
    this.subscribers.add(fn);
    return () => this.subscribers.delete(fn);
  }

  private notify(): void {
    for (const sub of this.subscribers) {
      try {
        sub(this.state);
      } catch (e) {
        console.error("AuthStore subscriber error:", e);
      }
    }
  }
}

export const authStore = new AuthStore();
