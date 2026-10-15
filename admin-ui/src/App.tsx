// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { PERMISSIONS } from "@/auth/permissions";
import { ThemeProvider } from "@/components/theme/ThemeProvider";
import { Toaster } from "sonner";

// Layout & Routes
import { AppShell } from "@/components/layout/AppShell";
import { Login } from "@/routes/Login";
import { Dashboard } from "@/features/dashboard/Dashboard";
import { DeviceList } from "@/features/devices/DeviceList";
import { DeviceDetail } from "@/features/devices/DeviceDetail";
import { UserList } from "@/features/users/UserList";
import { UserDetail } from "@/features/users/UserDetail";
import { ReEnrollReport } from "@/features/users/ReEnrollReport";
import { AuditLog } from "@/features/audit/AuditLog";
import { AdminAccounts } from "@/features/admins/AdminAccounts";
import { Settings } from "@/features/settings/Settings";
import { SystemStatus } from "@/features/status/SystemStatus";
import { MyAccount } from "@/features/account/MyAccount";
import { NotFound } from "@/routes/NotFound";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error: unknown) => {
        // Do not retry 401, 403, or 404 errors
        const status = (error as { status?: number })?.status;
        if (status === 401 || status === 403 || status === 404) {
          return false;
        }
        return failureCount < 2;
      },
      staleTime: 5000,
      refetchOnWindowFocus: true,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system" storageKey="freqid_ui_theme">
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              {/* Public route */}
              <Route path="/login" element={<Login />} />

              {/* Protected administrative routes */}
              <Route
                path="/"
                element={
                  <ProtectedRoute>
                    <AppShell />
                  </ProtectedRoute>
                }
              >
                <Route index element={<Navigate to="/dashboard" replace />} />
                <Route path="dashboard" element={<Dashboard />} />

                {/* Device management routes */}
                <Route path="devices" element={<DeviceList />} />
                <Route path="devices/:id" element={<DeviceDetail />} />

                {/* User identity & enrollment routes */}
                <Route
                  path="users"
                  element={
                    <ProtectedRoute requiredPermission={PERMISSIONS.USER_LIST}>
                      <UserList />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="users/:id"
                  element={
                    <ProtectedRoute requiredPermission={PERMISSIONS.USER_READ}>
                      <UserDetail />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="users/re-enroll"
                  element={
                    <ProtectedRoute requiredPermission={PERMISSIONS.USER_LIST}>
                      <ReEnrollReport />
                    </ProtectedRoute>
                  }
                />

                {/* Audit trail */}
                <Route
                  path="audit"
                  element={
                    <ProtectedRoute requiredPermission={PERMISSIONS.AUDIT_READ}>
                      <AuditLog />
                    </ProtectedRoute>
                  }
                />

                {/* Owner-only administrative management */}
                <Route
                  path="admin/accounts"
                  element={
                    <ProtectedRoute requiredPermission={PERMISSIONS.ADMIN_CREATE}>
                      <AdminAccounts />
                    </ProtectedRoute>
                  }
                />

                {/* Owner-only system settings */}
                <Route
                  path="admin/settings"
                  element={
                    <ProtectedRoute requiredPermission={PERMISSIONS.SETTINGS_UPDATE}>
                      <Settings />
                    </ProtectedRoute>
                  }
                />

                {/* Telemetry and profile */}
                <Route path="system/status" element={<SystemStatus />} />
                <Route path="account" element={<MyAccount />} />

                {/* 404 within app shell */}
                <Route path="*" element={<NotFound />} />
              </Route>

              {/* Top-level catch all */}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </BrowserRouter>
          <Toaster position="top-right" richColors closeButton />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
};
