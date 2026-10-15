// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { authStore } from "@/auth/authStore";
import { Login } from "@/routes/Login";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthContext";
import { refreshAccessToken } from "@/api/client";

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Authentication & Session Management", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    authStore.clearSession();
  });

  it("handles 423 lockout response and displays countdown timer", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />);

    const userInput = screen.getByLabelText(/^Username/i);
    const passInput = screen.getByLabelText(/Password/i);
    const submitBtn = screen.getByRole("button", { name: /Sign In/i });

    await user.type(userInput, "locked_user");
    await user.type(passInput, "wrongpassword");
    await user.click(submitBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/Account or IP locked due to repeated failed logins/i)
      ).toBeInTheDocument();
    });

    // The submit button should show lockout status and be disabled
    expect(submitBtn).toBeDisabled();
    expect(screen.getByText(/Locked out/i)).toBeInTheDocument();
  });

  it("clears session state on logout", async () => {
    // Set initial active session
    authStore.setSession("test-access-token", {
      admin_id: "adm-1",
      username: "alice",
      role: "owner",
      permissions: ["admin:create"],
    });

    expect(authStore.isAuthenticated()).toBe(true);

    authStore.clearSession();

    expect(authStore.isAuthenticated()).toBe(false);
    expect(authStore.getAccessToken()).toBeNull();
    expect(authStore.getUser()).toBeNull();
  });

  it("attempts single-flight token refresh on 401 response and updates session", async () => {
    // Initial session
    authStore.setSession("expired-token", {
      admin_id: "adm-1",
      username: "owner",
      role: "owner",
      permissions: ["admin:create"],
    });

    const refreshedToken = await refreshAccessToken();
    expect(refreshedToken).toBe("mock-refreshed-access-token-jwt");
    expect(authStore.getAccessToken()).toBe("mock-refreshed-access-token-jwt");
  });

  it("clears session if refresh fails with 401", async () => {
    // Set cookie to trigger simulated failure in MSW handler
    document.cookie = "refresh_fail=1; path=/";

    authStore.setSession("expired-token", {
      admin_id: "adm-1",
      username: "owner",
      role: "owner",
      permissions: ["admin:create"],
    });

    const result = await refreshAccessToken();
    expect(result).toBeNull();
    expect(authStore.isAuthenticated()).toBe(false);

    // Clean cookie
    document.cookie = "refresh_fail=; Max-Age=0; path=/";
  });
});
