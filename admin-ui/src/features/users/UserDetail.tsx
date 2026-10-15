// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getApiBaseUrl } from "@/api/client";
import { authStore } from "@/auth/authStore";
import { useCan } from "@/auth/useCan";
import { PERMISSIONS } from "@/auth/permissions";
import { PageHeader } from "@/components/layout/PageHeader";
import { DeleteUserDialog } from "./DeleteUserDialog";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowLeft,
  User,
  ShieldCheck,
  UserX,
  UserCheck,
  Trash2,
  Download,
  AlertTriangle,
  Activity,
  Sparkles,
} from "lucide-react";
import { formatExactTimestamp, formatRelativeTime } from "@/lib/formatters";
import { toast } from "sonner";
import type { UserSummary, AuditEventItem } from "@/api/models";

export const UserDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  const canModify = useCan(PERMISSIONS.USER_DISABLE);
  const canDelete = useCan(PERMISSIONS.USER_DELETE);

  const { data: user, isLoading } = useQuery<UserSummary>({
    queryKey: ["admin", "user", id],
    queryFn: async () => {
      if (!id) throw new Error("User ID required");
      const res = await api.GET("/v1/admin/users/{user_id}", {
        params: { path: { user_id: id } },
      });
      return res.data as unknown as UserSummary;
    },
    enabled: Boolean(id),
  });

  const { data: userAudit } = useQuery({
    queryKey: ["admin", "audit", "user", id],
    queryFn: async () => {
      if (!id) return null;
      const res = await api.GET("/v1/admin/audit", {
        params: { query: { user_id: id, limit: 10 } },
      });
      return res.data;
    },
    enabled: Boolean(id),
  });

  // Query system status to determine active model version
  const { data: statusData } = useQuery({
    queryKey: ["admin", "system", "status"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/system/status");
      return res.data;
    },
  });

  // Disable user mutation
  const disableMutation = useMutation({
    mutationFn: async () => {
      if (!id) return;
      await api.POST("/v1/admin/users/{user_id}/disable", {
        params: { path: { user_id: id } },
      });
    },
    onSuccess: () => {
      toast.success("User identity disabled");
      queryClient.invalidateQueries({ queryKey: ["admin", "user", id] });
    },
  });

  // Enable user mutation
  const enableMutation = useMutation({
    mutationFn: async () => {
      if (!id) return;
      await api.POST("/v1/admin/users/{user_id}/enable", {
        params: { path: { user_id: id } },
      });
    },
    onSuccess: () => {
      toast.success("User identity re-enabled");
      queryClient.invalidateQueries({ queryKey: ["admin", "user", id] });
    },
  });

  // Delete user mutation
  const deleteMutation = useMutation({
    mutationFn: async (userId: string) => {
      await api.DELETE("/v1/admin/users/{user_id}", {
        params: { path: { user_id: userId } },
      });
    },
    onSuccess: () => {
      toast.success("User identity permanently erased");
      navigate("/users", { replace: true });
    },
  });

  const handleExportData = async () => {
    if (!id || !user) return;
    try {
      const baseUrl = getApiBaseUrl();
      const token = authStore.getAccessToken();
      const res = await fetch(`${baseUrl}/v1/admin/users/${id}/export`, {
        headers: {
          Authorization: token ? `Bearer ${token}` : "",
        },
      });

      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `freqid_user_${user.external_id}_export.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Data export downloaded (GDPR Article 15)");
    } catch {
      toast.error("Failed to export user metadata");
    }
  };

  const activeModel = statusData?.model_version || "partialface_ir18_v1";
  const userModel = user?.model_version || "partialface_ir18_v1";
  const needsReEnrollment = userModel !== activeModel;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="space-y-4 text-center py-12">
        <AlertTriangle className="h-10 w-10 text-muted-foreground mx-auto" />
        <h2 className="text-lg font-semibold">User Not Found</h2>
        <p className="text-sm text-muted-foreground">The requested identity could not be located.</p>
        <Button variant="outline" onClick={() => navigate("/users")}>
          Return to Identity List
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/users" className="flex items-center gap-1 text-muted-foreground">
            <ArrowLeft className="h-4 w-4" />
            <span>Back to Users</span>
          </Link>
        </Button>
      </div>

      <PageHeader
        title={`User: ${user.external_id}`}
        description={`Internal UUID: ${user.id}`}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportData}
              className="flex items-center gap-1.5"
            >
              <Download className="h-4 w-4" />
              <span>Export Metadata</span>
            </Button>

            {user.is_active && canModify && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => disableMutation.mutate()}
                disabled={disableMutation.isPending}
                className="text-amber-600 border-amber-600/30 hover:bg-amber-500/10"
              >
                <UserX className="h-4 w-4 mr-1.5" />
                Disable User
              </Button>
            )}

            {!user.is_active && canModify && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => enableMutation.mutate()}
                disabled={enableMutation.isPending}
                className="text-emerald-600 border-emerald-600/30 hover:bg-emerald-500/10"
              >
                <UserCheck className="h-4 w-4 mr-1.5" />
                Re-enable User
              </Button>
            )}

            {canDelete && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setShowDeleteDialog(true)}
              >
                <Trash2 className="h-4 w-4 mr-1.5" />
                Delete (Erasure)
              </Button>
            )}
          </div>
        }
      />

      {/* Model Re-Enrollment Warning Banner */}
      {needsReEnrollment && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-700 dark:text-amber-400 flex items-start gap-3">
          <Sparkles className="h-5 w-5 shrink-0 mt-0.5 text-amber-500" />
          <div className="space-y-1">
            <h4 className="font-semibold text-sm">Model Re-Enrollment Recommended</h4>
            <p className="leading-relaxed">
              This subject was enrolled using model version{" "}
              <code className="font-mono font-semibold">{userModel}</code>, while the active system
              backbone is currently{" "}
              <code className="font-mono font-semibold">{activeModel}</code>. The subject should be
              re-captured at an enrollment terminal to ensure optimal recognition accuracy.
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {/* Identity Details Card */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <User className="h-4 w-4 text-primary" />
              <span>Identity Profile</span>
            </CardTitle>
            <CardDescription>Biometric subject registration and status</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">External Identifier</span>
              <span className="font-mono font-semibold text-foreground">{user.external_id}</span>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Account Status</span>
              <Badge variant={user.is_active ? "success" : "warning"}>
                {user.is_active ? "Active" : "Disabled"}
              </Badge>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Enrolled Timestamp</span>
              <span>{formatExactTimestamp(user.created_at)}</span>
            </div>

            <div className="flex justify-between py-1.5">
              <span className="text-muted-foreground">Last Modified</span>
              <span>
                {formatRelativeTime(user.updated_at)} ({formatExactTimestamp(user.updated_at)})
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Template & Quality Card */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" />
              <span>Template Cryptographic Status</span>
            </CardTitle>
            <CardDescription>Envelope encryption and synthesized sample statistics</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Biometric Backbone Model</span>
              <span className="font-mono text-foreground font-medium">{userModel}</span>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Synthesized Enrollment Samples</span>
              <span className="font-medium">{user.sample_count || 1} frame(s)</span>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Encryption Scheme</span>
              <Badge variant="outline">AES-256-GCM (Per-Template DEK)</Badge>
            </div>

            <div className="flex justify-between py-1.5">
              <span className="text-muted-foreground">Authenticated Additional Data (AAD)</span>
              <span className="font-mono text-xs text-muted-foreground">
                SHA256(user_id:model)
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Privacy Guarantee Invariant Box */}
      <div className="rounded-lg border bg-muted/30 p-4 text-xs text-muted-foreground space-y-1">
        <h5 className="font-semibold text-foreground">Zero Biometric Exposure Guarantee:</h5>
        <p>• Raw face images and full spatial tensors are never stored in the database or rendered in the browser.</p>
        <p>• Biometric 512-D float vectors are stored as ciphertext in PostgreSQL and are never sent over the Admin API.</p>
      </div>

      {/* User Verification Audit History */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <span>Recent Verification Activity</span>
          </CardTitle>
          <CardDescription>Audit records where this identity was claimed or matched</CardDescription>
        </CardHeader>
        <CardContent>
          {userAudit?.items && userAudit.items.length > 0 ? (
            <div className="divide-y divide-border text-xs">
              {(userAudit.items as unknown as AuditEventItem[]).map((ev) => (
                <div key={ev.id} className="py-2.5 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="font-medium text-foreground flex items-center gap-2">
                      <span className="capitalize">{ev.event_type.replace(/_/g, " ")}</span>
                      <Badge variant={ev.decision === "verified" ? "success" : "destructive"}>
                        {ev.decision}
                      </Badge>
                    </div>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      Req ID: {ev.request_id || ev.id}
                    </p>
                  </div>
                  <span className="text-muted-foreground">
                    {formatRelativeTime(ev.event_time)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No verification audit records currently found for this user.
            </p>
          )}
        </CardContent>
      </Card>

      {/* GDPR Delete Dialog */}
      <DeleteUserDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        user={{ id: user.id, external_id: user.external_id }}
        onConfirm={async (userId: string) => {
          await deleteMutation.mutateAsync(userId);
        }}
        isLoading={deleteMutation.isPending}
      />
    </div>
  );
};
