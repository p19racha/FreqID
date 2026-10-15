// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { authStore } from "@/auth/authStore";
import { AuthProvider } from "@/auth/AuthContext";
import { DeviceList } from "@/features/devices/DeviceList";
import { DeviceStatusBadge } from "@/features/devices/DeviceStatusBadge";
import { RevokeDeviceDialog } from "@/features/devices/RevokeDeviceDialog";

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

describe("Device Fleet Management (Hard Rules & UX)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    authStore.clearSession();
    // Set authenticated owner by default
    authStore.setSession("mock-owner-token", {
      admin_id: "adm-1",
      username: "owner",
      role: "owner",
      permissions: [
        "device:list",
        "device:create_pairing_token",
        "device:revoke",
        "device:approve",
      ],
    });
  });

  it("renders status badges correctly for each device lifecycle state", () => {
    const recent = new Date().toISOString();
    const { rerender } = render(<DeviceStatusBadge state="active" lastSeen={recent} />);
    expect(screen.getByText(/^Active$/i)).toBeInTheDocument();

    rerender(<DeviceStatusBadge state="pending" />);
    expect(screen.getByText(/^Pending$/i)).toBeInTheDocument();

    rerender(<DeviceStatusBadge state="suspended" />);
    expect(screen.getByText(/^Suspended$/i)).toBeInTheDocument();

    rerender(<DeviceStatusBadge state="revoked" />);
    expect(screen.getByText(/^Revoked$/i)).toBeInTheDocument();
  });

  it("loads and renders registered edge devices in DeviceList table", async () => {
    renderWithProviders(<DeviceList />);

    // Wait for mock devices to load from MSW handler
    await waitFor(() => {
      expect(screen.getByText("lobby-turnstile-cam-01")).toBeInTheDocument();
      expect(screen.getByText("gate-north-cam-02")).toBeInTheDocument();
    });

    // Check presence of status badges in table
    const table = screen.getByRole("table");
    expect(within(table).getByText(/^Active$/i)).toBeInTheDocument();
    expect(within(table).getByText(/^Pending$/i)).toBeInTheDocument();
  });

  it("enforces exact device name typing before allowing permanent revocation", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const mockOnConfirm = vi.fn().mockResolvedValue(undefined);
    let open = true;

    const device = {
      id: "dev-001",
      name: "edge-turnstile-entrance",
    };

    render(
      <RevokeDeviceDialog
        open={open}
        onOpenChange={(val) => {
          open = val;
        }}
        device={device}
        onConfirm={mockOnConfirm}
      />
    );

    // Initial state: Title and Warning notice visible
    expect(screen.getByText(/Permanently Revoke Edge Device\?/i)).toBeInTheDocument();
    const revokeBtn = screen.getByRole("button", { name: /Revoke Device Permanently/i });

    // Confirm button must be disabled initially
    expect(revokeBtn).toBeDisabled();

    // Partial or incorrect name typed
    const input = screen.getByLabelText(/to confirm:/i);
    await user.type(input, "edge-turnstile");
    expect(revokeBtn).toBeDisabled();

    // Exact name typed
    await user.clear(input);
    await user.type(input, "edge-turnstile-entrance");

    expect(revokeBtn).toBeEnabled();

    // Fill revocation reason
    const reasonInput = screen.getByLabelText(/Reason for revocation:/i);
    await user.type(reasonInput, "Decommissioned hardware unit");

    // Click revoke button
    fireEvent.click(revokeBtn);

    await waitFor(() => {
      expect(mockOnConfirm).toHaveBeenCalledWith(
        "dev-001",
        "Decommissioned hardware unit"
      );
    });
  });
});
