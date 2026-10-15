// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useCan } from "@/auth/useCan";
import { PERMISSIONS } from "@/auth/permissions";
import { PageHeader } from "@/components/layout/PageHeader";
import { DeleteUserDialog } from "./DeleteUserDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Search,
  MoreHorizontal,
  Eye,
  UserCheck,
  UserX,
  Trash2,
  RefreshCw,
  Users,
  Info,
  ArrowRight,
  FileSpreadsheet,
} from "lucide-react";
import { formatRelativeTime } from "@/lib/formatters";
import { toast } from "sonner";
import type { UserSummary } from "@/api/models";

export const UserList: React.FC = () => {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [searchId, setSearchId] = useState("");
  const [activeFilter, setActiveFilter] = useState<string>("all");
  const [userToDelete, setUserToDelete] = useState<{ id: string; external_id: string } | null>(null);

  const queryClient = useQueryClient();
  const canModifyUser = useCan(PERMISSIONS.USER_DISABLE);
  const canDeleteUser = useCan(PERMISSIONS.USER_DELETE);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/users", {
        params: {
          query: {
            limit: 200,
          },
        },
      });
      return (res.data || []) as unknown as UserSummary[];
    },
    refetchInterval: 30000,
  });

  // Disable user mutation
  const disableMutation = useMutation({
    mutationFn: async (userId: string) => {
      await api.POST("/v1/admin/users/{user_id}/disable", {
        params: { path: { user_id: userId } },
      });
    },
    onSuccess: () => {
      toast.success("User account disabled");
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to disable user", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  // Enable user mutation
  const enableMutation = useMutation({
    mutationFn: async (userId: string) => {
      await api.POST("/v1/admin/users/{user_id}/enable", {
        params: { path: { user_id: userId } },
      });
    },
    onSuccess: () => {
      toast.success("User account enabled");
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to enable user", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  // Delete user mutation (GDPR Article 17)
  const deleteMutation = useMutation({
    mutationFn: async (userId: string) => {
      await api.DELETE("/v1/admin/users/{user_id}", {
        params: { path: { user_id: userId } },
      });
    },
    onSuccess: () => {
      toast.success("User identity and templates permanently deleted");
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to delete user", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  const allUsers: UserSummary[] = Array.isArray(data)
    ? data
    : ((data as unknown as { items?: UserSummary[] })?.items || []);
  const filteredUsers = allUsers.filter((u: UserSummary) => {
    if (activeFilter === "active" && !u.is_active) return false;
    if (activeFilter === "inactive" && u.is_active) return false;
    if (searchId.trim()) {
      const q = searchId.trim().toLowerCase();
      return (
        (u.external_id && u.external_id.toLowerCase().includes(q)) ||
        (u.id && u.id.toLowerCase().includes(q))
      );
    }
    return true;
  });

  const total = filteredUsers.length;
  const totalPages = Math.ceil(total / pageSize) || 1;
  const users = filteredUsers.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Identity & Enrollment Registry"
        description="Search, inspect, and manage registered biometric identities and GDPR data rights."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              asChild
            >
              <Link to="/users/re-enroll">
                <FileSpreadsheet className="h-4 w-4 mr-1.5" />
                Re-Enrollment Report
              </Link>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        }
      />

      {/* Informational Guidance Panel (Hard Rule 1: No Browser Enrollment) */}
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 text-xs flex items-start gap-3">
        <Info className="h-5 w-5 text-primary shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h4 className="font-semibold text-foreground text-sm">
            How Identities are Enrolled in FreqID
          </h4>
          <p className="text-muted-foreground leading-relaxed">
            By cryptographic design, <strong>the browser never captures or uploads facial images</strong>.
            New subjects must present themselves at an authorized edge terminal provisioned with the{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-foreground font-semibold">enroll</code>{" "}
            scope (such as an administrative registration kiosk). The edge hardware converts the face
            directly into 27-channel partial frequency payloads and transmits them over TLS.
          </p>
          <div className="pt-1">
            <Link
              to="/devices"
              className="text-primary font-medium hover:underline inline-flex items-center gap-1"
            >
              View authorized enrollment terminals <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by external ID..."
              value={searchId}
              onChange={(e) => {
                setSearchId(e.target.value);
                setPage(1);
              }}
              className="pl-9 h-9"
            />
          </div>

          <select
            value={activeFilter}
            onChange={(e) => {
              setActiveFilter(e.target.value);
              setPage(1);
            }}
            className="h-9 rounded-md border border-input bg-transparent px-3 py-1 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
          >
            <option value="all">All Users</option>
            <option value="active">Active Only</option>
            <option value="disabled">Disabled Only</option>
          </select>
        </div>

        <div className="text-xs text-muted-foreground self-end sm:self-center">
          Showing <span className="font-semibold text-foreground">{users.length}</span> of{" "}
          <span className="font-semibold text-foreground">{total}</span> users
        </div>
      </div>

      {/* Table Section */}
      <div className="rounded-lg border bg-card shadow-sm">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User / External ID</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Model Version</TableHead>
              <TableHead>Samples</TableHead>
              <TableHead>Enrolled At</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell><Skeleton className="h-5 w-36" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-20" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-24" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-12" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-24" /></TableCell>
                  <TableCell className="text-right"><Skeleton className="h-8 w-8 ml-auto" /></TableCell>
                </TableRow>
              ))
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                  <div className="flex flex-col items-center justify-center space-y-2">
                    <Users className="h-8 w-8 text-muted-foreground/50" />
                    <p className="text-sm font-medium">No enrolled users found</p>
                    <p className="text-xs text-muted-foreground">
                      {searchId || activeFilter !== "all"
                        ? "Try adjusting your search criteria."
                        : "Enroll new users using a paired edge client terminal."}
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="font-medium text-foreground">
                      <Link
                        to={`/users/${user.id}`}
                        className="hover:underline hover:text-primary transition-colors font-mono"
                      >
                        {user.external_id}
                      </Link>
                    </div>
                    <div className="font-mono text-[10px] text-muted-foreground truncate max-w-[200px]">
                      {user.id}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={user.is_active ? "success" : "warning"} className="text-xs">
                      {user.is_active ? "Active" : "Disabled"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {user.model_version || "partialface_ir18_v1"}
                  </TableCell>
                  <TableCell className="text-xs font-medium">
                    {user.sample_count || 1}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatRelativeTime(user.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <MoreHorizontal className="h-4 w-4" />
                          <span className="sr-only">Actions</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem asChild>
                          <Link to={`/users/${user.id}`} className="flex items-center gap-2 cursor-pointer">
                            <Eye className="h-4 w-4" />
                            <span>View Profile</span>
                          </Link>
                        </DropdownMenuItem>

                        {canModifyUser && user.is_active && (
                          <DropdownMenuItem
                            onClick={() => disableMutation.mutate(user.id)}
                            className="flex items-center gap-2 cursor-pointer text-amber-600 focus:text-amber-600"
                          >
                            <UserX className="h-4 w-4" />
                            <span>Disable User</span>
                          </DropdownMenuItem>
                        )}

                        {canModifyUser && !user.is_active && (
                          <DropdownMenuItem
                            onClick={() => enableMutation.mutate(user.id)}
                            className="flex items-center gap-2 cursor-pointer text-emerald-600 focus:text-emerald-600"
                          >
                            <UserCheck className="h-4 w-4" />
                            <span>Re-enable User</span>
                          </DropdownMenuItem>
                        )}

                        {canDeleteUser && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => setUserToDelete({ id: user.id, external_id: user.external_id })}
                              className="text-destructive focus:bg-destructive/10 focus:text-destructive flex items-center gap-2 cursor-pointer"
                            >
                              <Trash2 className="h-4 w-4" />
                              <span>Delete (GDPR Erasure)</span>
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </Button>
          <span className="text-xs text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}

      {/* GDPR Delete Dialog */}
      <DeleteUserDialog
        open={userToDelete !== null}
        onOpenChange={(open) => !open && setUserToDelete(null)}
        user={userToDelete}
        onConfirm={async (id) => {
          await deleteMutation.mutateAsync(id);
        }}
        isLoading={deleteMutation.isPending}
      />
    </div>
  );
};
