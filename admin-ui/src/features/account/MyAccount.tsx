// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useSession } from "@/auth/AuthContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  KeyRound,
  Shield,
  LogOut,
  AlertCircle,
  Lock,
} from "lucide-react";
import { toast } from "sonner";

export const MyAccount: React.FC = () => {
  const { user, logoutEverywhere } = useSession();

  // Password change form
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pwdError, setPwdError] = useState<string | null>(null);

  const changePasswordMutation = useMutation({
    mutationFn: async () => {
      await api.POST("/v1/admin/auth/change-password", {
        body: {
          current_password: currentPassword,
          new_password: newPassword,
        },
      });
    },
    onSuccess: () => {
      toast.success("Password changed successfully");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPwdError(null);
    },
    onError: (err: unknown) => {
      setPwdError(err instanceof Error ? err.message : "Failed to change password");
      setCurrentPassword("");
    },
  });

  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPwdError(null);

    if (newPassword.length < 12) {
      setPwdError("New password must be at least 12 characters long.");
      return;
    }

    if (newPassword !== confirmPassword) {
      setPwdError("New password and confirmation do not match.");
      return;
    }

    changePasswordMutation.mutate();
  };

  const handleLogoutAll = async () => {
    if (confirm("Are you sure you want to invalidate all active sessions across all devices?")) {
      await logoutEverywhere();
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="My Account Profile"
        description="Manage your credentials, active session tokens, and security factors."
      />

      <div className="grid gap-6 md:grid-cols-2">
        {/* Profile Card */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Shield className="h-4 w-4 text-primary" />
              <span>Identity & Roles</span>
            </CardTitle>
            <CardDescription>Your current administrative assignment and privileges</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Username</span>
              <span className="font-semibold text-foreground font-mono">{user?.username}</span>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Assigned Role</span>
              <Badge variant="default" className="capitalize text-xs">
                {user?.role}
              </Badge>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Internal Admin UUID</span>
              <span className="font-mono text-xs text-muted-foreground truncate max-w-[200px]">
                {user?.admin_id}
              </span>
            </div>

            <div className="py-2 space-y-1.5">
              <span className="text-xs text-muted-foreground font-medium block">
                Granted System Permissions ({user?.permissions?.length || 0}):
              </span>
              <div className="flex flex-wrap gap-1 max-h-36 overflow-y-auto p-1.5 rounded border bg-muted/30">
                {user?.permissions?.map((p) => (
                  <Badge key={p} variant="outline" className="font-mono text-[10px] px-1 py-0">
                    {p}
                  </Badge>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Change Password Form */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-primary" />
              <span>Rotate Password</span>
            </CardTitle>
            <CardDescription>Update your Argon2id-hashed authentication credentials</CardDescription>
          </CardHeader>

          <form onSubmit={handlePasswordSubmit}>
            <CardContent className="space-y-4">
              {pwdError && (
                <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{pwdError}</span>
                </div>
              )}

              <div className="space-y-1.5">
                <Label htmlFor="current-pwd">Current Password *</Label>
                <Input
                  id="current-pwd"
                  type="password"
                  required
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="new-pwd">New Password *</Label>
                <Input
                  id="new-pwd"
                  type="password"
                  required
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
                <p className="text-[11px] text-muted-foreground">
                  Minimum 12 characters. Checked against common password dictionaries.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="confirm-pwd">Confirm New Password *</Label>
                <Input
                  id="confirm-pwd"
                  type="password"
                  required
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </div>
            </CardContent>

            <CardFooter className="border-t pt-4 flex justify-end">
              <Button type="submit" disabled={changePasswordMutation.isPending}>
                {changePasswordMutation.isPending ? "Updating..." : "Update Password"}
              </Button>
            </CardFooter>
          </form>
        </Card>
      </div>

      {/* Active Sessions & Security Controls */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Lock className="h-4 w-4 text-primary" />
            <span>Active Sessions & Emergency Controls</span>
          </CardTitle>
          <CardDescription>
            Manage active refresh token families across browsers and workstations
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 rounded-lg border bg-muted/20">
            <div className="space-y-0.5">
              <div className="text-sm font-semibold text-foreground">Sign Out Everywhere</div>
              <p className="text-xs text-muted-foreground">
                Revokes all active refresh token families for your account in PostgreSQL. You will need to log in again on all devices.
              </p>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleLogoutAll}
              className="shrink-0 flex items-center gap-1.5"
            >
              <LogOut className="h-4 w-4" />
              <span>Sign Out All Sessions</span>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
