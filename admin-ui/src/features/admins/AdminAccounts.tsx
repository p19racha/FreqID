// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useSession } from "@/auth/AuthContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  UserPlus,
  Unlock,
  Copy,
  Check,
  AlertTriangle,
  RefreshCw,
  Lock,
} from "lucide-react";
import { formatRelativeTime } from "@/lib/formatters";
import { toast } from "sonner";
import { AdminAccountItem } from "@/api/models";

export const AdminAccounts: React.FC = () => {
  const { user: currentAdmin } = useSession();
  const queryClient = useQueryClient();

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newRole, setNewRole] = useState<"admin" | "operator" | "auditor">("operator");
  const [generatedPassword, setGeneratedPassword] = useState<string | null>(null);
  const [copiedPwd, setCopiedPwd] = useState(false);

  const { data: admins, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["admin", "admins"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/admins");
      return (res.data || []) as AdminAccountItem[];
    },
  });

  // Create admin mutation
  const createMutation = useMutation({
    mutationFn: async ({ username, role, password }: { username: string; role: string; password: string }) => {
      await api.POST("/v1/admin/admins", {
        body: { username, role, password },
      });
    },
    onSuccess: () => {
      toast.success("Administrator account created");
      queryClient.invalidateQueries({ queryKey: ["admin", "admins"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to create admin account", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  // Unlock admin mutation
  const unlockMutation = useMutation({
    mutationFn: async (adminId: string) => {
      await api.POST("/v1/admin/admins/{admin_id}/unlock", {
        params: { path: { admin_id: adminId } },
      });
    },
    onSuccess: () => {
      toast.success("Account unlocked");
      queryClient.invalidateQueries({ queryKey: ["admin", "admins"] });
    },
  });

  // Toggle active status mutation
  const toggleStatusMutation = useMutation({
    mutationFn: async ({ adminId, isActive }: { adminId: string; isActive: boolean }) => {
      await api.PATCH("/v1/admin/admins/{admin_id}", {
        params: { path: { admin_id: adminId } },
        body: { is_active: isActive },
      });
    },
    onSuccess: () => {
      toast.success("Account status updated");
      queryClient.invalidateQueries({ queryKey: ["admin", "admins"] });
    },
    onError: (err: unknown) => {
      toast.error("Status update rejected", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim()) return;

    // Generate secure 16-character temporary password
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#$%";
    let tempPwd = "";
    for (let i = 0; i < 16; i++) {
      tempPwd += chars.charAt(Math.floor(Math.random() * chars.length));
    }

    try {
      await createMutation.mutateAsync({
        username: newUsername.trim(),
        role: newRole,
        password: tempPwd,
      });
      setGeneratedPassword(tempPwd);
    } catch {
      // Handled by onError
    }
  };

  const copyPassword = () => {
    if (!generatedPassword) return;
    navigator.clipboard.writeText(generatedPassword);
    setCopiedPwd(true);
    setTimeout(() => setCopiedPwd(false), 2000);
  };

  const handleCloseCreateModal = () => {
    setIsCreateOpen(false);
    setNewUsername("");
    setNewRole("operator");
    setGeneratedPassword(null);
    setCopiedPwd(false);
  };

  const roleVariant = (role: string) => {
    switch (role) {
      case "owner":
        return "destructive";
      case "admin":
        return "default";
      case "operator":
        return "secondary";
      case "auditor":
        return "outline";
      default:
        return "secondary";
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Administrator Accounts & RBAC"
        description="Owner-only management of system operators, auditors, and administrators."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button size="sm" onClick={() => setIsCreateOpen(true)}>
              <UserPlus className="h-4 w-4 mr-1.5" />
              New Admin
            </Button>
          </div>
        }
      />

      {/* Role Privilege Reference Banner */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
        <div className="p-3 rounded-lg border bg-card">
          <Badge variant="destructive" className="mb-1 text-[10px]">OWNER</Badge>
          <p className="text-muted-foreground mt-1">Full control over settings, owner accounts, and system thresholds.</p>
        </div>
        <div className="p-3 rounded-lg border bg-card">
          <Badge variant="default" className="mb-1 text-[10px]">ADMIN</Badge>
          <p className="text-muted-foreground mt-1">Manage edge devices, pairing tokens, user enrollments, and GDPR erasure.</p>
        </div>
        <div className="p-3 rounded-lg border bg-card">
          <Badge variant="secondary" className="mb-1 text-[10px]">OPERATOR</Badge>
          <p className="text-muted-foreground mt-1">Enroll station operator. View system status and enrolled identities.</p>
        </div>
        <div className="p-3 rounded-lg border bg-card">
          <Badge variant="outline" className="mb-1 text-[10px]">AUDITOR</Badge>
          <p className="text-muted-foreground mt-1">Compliance officer. Read-only access to tamper-evident audit logs and CSV export.</p>
        </div>
      </div>

      {/* Admin Accounts Table */}
      <div className="rounded-lg border bg-card shadow-sm">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Username</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Failed Logins</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell><Skeleton className="h-5 w-24" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-16" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-16" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-12" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-20" /></TableCell>
                  <TableCell className="text-right"><Skeleton className="h-8 w-20 ml-auto" /></TableCell>
                </TableRow>
              ))
            ) : admins?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center text-muted-foreground">
                  No administrator accounts found.
                </TableCell>
              </TableRow>
            ) : (
              admins?.map((admin: AdminAccountItem) => {
                const isLocked = admin.locked_until && new Date(admin.locked_until).getTime() > Date.now();
                const isSelf = admin.username === currentAdmin?.username;

                return (
                  <TableRow key={admin.id}>
                    <TableCell className="font-medium text-foreground">
                      <div className="flex items-center gap-2">
                        <span>{admin.username}</span>
                        {isSelf && (
                          <Badge variant="outline" className="text-[10px] px-1 py-0">You</Badge>
                        )}
                      </div>
                    </TableCell>

                    <TableCell>
                      <Badge variant={roleVariant(admin.role)} className="capitalize text-xs">
                        {admin.role}
                      </Badge>
                    </TableCell>

                    <TableCell>
                      {isLocked ? (
                        <Badge variant="destructive" className="flex items-center gap-1 w-fit text-xs">
                          <Lock className="h-3 w-3" />
                          <span>Locked</span>
                        </Badge>
                      ) : (
                        <Badge variant={admin.is_active ? "success" : "warning"} className="text-xs">
                          {admin.is_active ? "Active" : "Disabled"}
                        </Badge>
                      )}
                    </TableCell>

                    <TableCell className="text-xs font-mono">
                      {admin.failed_logins ?? 0}
                    </TableCell>

                    <TableCell className="text-xs text-muted-foreground">
                      {formatRelativeTime(admin.created_at)}
                    </TableCell>

                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {isLocked && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs flex items-center gap-1 text-emerald-600 border-emerald-600/30"
                            onClick={() => unlockMutation.mutate(admin.id)}
                            disabled={unlockMutation.isPending}
                          >
                            <Unlock className="h-3 w-3" />
                            <span>Unlock</span>
                          </Button>
                        )}

                        {!isSelf && admin.role !== "owner" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs text-muted-foreground hover:text-foreground"
                            onClick={() =>
                              toggleStatusMutation.mutate({
                                adminId: admin.id,
                                isActive: !admin.is_active,
                              })
                            }
                            disabled={toggleStatusMutation.isPending}
                          >
                            {admin.is_active ? "Disable" : "Enable"}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Create Admin Modal */}
      <Dialog open={isCreateOpen} onOpenChange={handleCloseCreateModal}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserPlus className="h-5 w-5 text-primary" />
              <span>Provision Administrator Account</span>
            </DialogTitle>
            <DialogDescription>
              Create a new administrative user and assign a privilege tier.
            </DialogDescription>
          </DialogHeader>

          {!generatedPassword ? (
            <form onSubmit={handleCreateSubmit} className="space-y-4 py-2">
              <div className="space-y-2">
                <Label htmlFor="admin-username">Username *</Label>
                <Input
                  id="admin-username"
                  required
                  placeholder="e.g. john_doe"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  autoFocus
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="admin-role">Role Privilege Level *</Label>
                <select
                  id="admin-role"
                  className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as "admin" | "operator" | "auditor")}
                >
                  <option value="operator">Operator (Enrollment station & status)</option>
                  <option value="admin">Administrator (Device & user management)</option>
                  <option value="auditor">Auditor (Compliance & audit export)</option>
                </select>
              </div>

              <DialogFooter className="pt-2">
                <Button type="button" variant="outline" onClick={handleCloseCreateModal}>
                  Cancel
                </Button>
                <Button type="submit" disabled={createMutation.isPending || !newUsername.trim()}>
                  {createMutation.isPending ? "Provisioning..." : "Create Account"}
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="space-y-4 py-2">
              {/* Security Warning (Hard Rule 4) */}
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-600 dark:text-amber-400 flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold">Temporary Credentials: </span>
                  This initial temporary password is shown <strong>once</strong>. Share it securely with
                  the administrator; they will be prompted to change it upon first login.
                </div>
              </div>

              <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
                <div className="text-xs text-muted-foreground font-medium">Temporary Password</div>
                <div className="flex items-center gap-2">
                  <div className="font-mono text-sm font-semibold tracking-wider bg-background px-3 py-2 rounded border flex-1 select-all truncate">
                    {generatedPassword}
                  </div>
                  <Button variant="outline" size="sm" onClick={copyPassword} className="h-9">
                    {copiedPwd ? <Check className="h-4 w-4 text-emerald-500 mr-1" /> : <Copy className="h-4 w-4 mr-1" />}
                    {copiedPwd ? "Copied" : "Copy"}
                  </Button>
                </div>
              </div>

              <DialogFooter className="pt-2">
                <Button onClick={handleCloseCreateModal} className="w-full">
                  Done
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};
