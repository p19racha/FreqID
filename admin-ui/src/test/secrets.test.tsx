// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { authStore } from "@/auth/authStore";
import { AddDeviceWizard } from "@/features/devices/AddDeviceWizard";
import { Login } from "@/routes/Login";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthContext";

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

describe("Security Invariants & Secret Storage (Hard Rules 3 & 4)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    authStore.clearSession();
  });

  it("stores access tokens only in volatile memory, never in localStorage or sessionStorage", () => {
    // Check initial state
    expect(authStore.getAccessToken()).toBeNull();
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(sessionStorage.getItem("access_token")).toBeNull();

    // Set auth in memory
    authStore.setSession("test-jwt-secret-token", {
      admin_id: "usr-1",
      username: "owner",
      role: "owner",
      permissions: [],
    });

    // In-memory getter succeeds
    expect(authStore.getAccessToken()).toBe("test-jwt-secret-token");
    expect(authStore.getUser()?.username).toBe("owner");

    // CRITICAL: Web Storage MUST be completely empty of secrets
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("token")).toBeNull();
    expect(localStorage.getItem("auth")).toBeNull();
    expect(sessionStorage.getItem("access_token")).toBeNull();
    expect(sessionStorage.getItem("token")).toBeNull();
    expect(sessionStorage.getItem("auth")).toBeNull();

    // Verify localStorage has no keys matching any token pattern
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      expect(key).not.toMatch(/token|secret|auth|jwt/i);
    }

    // Verify sessionStorage has no keys matching any token pattern
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      expect(key).not.toMatch(/token|secret|auth|jwt/i);
    }

    // Clear wipes memory
    authStore.clearSession();
    expect(authStore.getAccessToken()).toBeNull();
    expect(authStore.getUser()).toBeNull();
  });


  it("does not write secrets to localStorage or sessionStorage during Login flow", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />);

    const userInput = screen.getByLabelText(/^Username/i);
    const passInput = screen.getByLabelText(/Password/i);
    const submitBtn = screen.getByRole("button", { name: /Sign In/i });

    await user.type(userInput, "owner");
    await user.type(passInput, "CorrectPassword123!");
    await user.click(submitBtn);

    await waitFor(() => {
      expect(authStore.getAccessToken()).toBe("mock-valid-access-token-jwt-secret");
    });

    // Verify localStorage & sessionStorage remain 100% clean
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("proves pairing tokens in AddDeviceWizard exist only during modal lifecycle and are cleared upon close", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    let isOpen = true;
    const handleOpenChange = (open: boolean) => {
      isOpen = open;
    };

    const queryClient = new QueryClient();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <AddDeviceWizard open={isOpen} onOpenChange={handleOpenChange} />
      </QueryClientProvider>
    );

    // Step 1: Type device name and submit
    const nameInput = screen.getByLabelText(/Device Name \/ Location/i);
    await user.type(nameInput, "lobby-cam-01");

    const form = nameInput.closest("form")!;
    fireEvent.submit(form);

    // Step 2: Pairing token is displayed once in the modal
    await waitFor(() => {
      const tokens = screen.getAllByText((content) =>
        content.includes("pair-128bit-secret-token-random-value")
      );
      expect(tokens.length).toBeGreaterThan(0);
    });

    // Check localStorage & sessionStorage: zero secrets
    expect(localStorage.getItem("pairing_token")).toBeNull();
    expect(sessionStorage.getItem("pairing_token")).toBeNull();

    // Close the dialog
    rerender(
      <QueryClientProvider client={queryClient}>
        <AddDeviceWizard open={false} onOpenChange={handleOpenChange} />
      </QueryClientProvider>
    );

    // Reopen dialog: sensitive state must be completely cleared
    rerender(
      <QueryClientProvider client={queryClient}>
        <AddDeviceWizard open={true} onOpenChange={handleOpenChange} />
      </QueryClientProvider>
    );

    // Should be back at step 1
    expect(screen.getByLabelText(/Device Name \/ Location/i)).toHaveValue("");
    expect(screen.queryByText(/pair-128bit-secret-token-random-value/i)).not.toBeInTheDocument();
  });
});
