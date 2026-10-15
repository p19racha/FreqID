// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useCan } from "@/auth/useCan";
import { PERMISSIONS } from "@/auth/permissions";
import { PageHeader } from "@/components/layout/PageHeader";
import { DeviceStatusBadge } from "./DeviceStatusBadge";
import { AddDeviceWizard } from "./AddDeviceWizard";
import { RevokeDeviceDialog } from "./RevokeDeviceDialog";
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
  Plus,
  Search,
  MoreHorizontal,
  Eye,
  PauseCircle,
  PlayCircle,
  XCircle,
  RefreshCw,
  Camera,
  Filter,
  CheckCircle,
} from "lucide-react";
import { toast } from "sonner";
import type { DeviceSummary } from "@/api/models";

export const DeviceList: React.FC = () => {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [searchName, setSearchName] = useState("");
  const [stateFilter, setStateFilter] = useState<string>("all");
  const [isAddWizardOpen, setIsAddWizardOpen] = useState(false);
  const [deviceToRevoke, setDeviceToRevoke] = useState<{ id: string; name: string } | null>(null);

  const queryClient = useQueryClient();
  const canAddDevice = useCan(PERMISSIONS.DEVICE_CREATE_PAIRING);
  const canRevoke = useCan(PERMISSIONS.DEVICE_REVOKE);
  const canApprove = useCan(PERMISSIONS.DEVICE_APPROVE);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["admin", "devices", { stateFilter, searchName }],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/devices", {
        params: {
          query: {
            limit: 100,
            state: stateFilter === "all" ? undefined : stateFilter,
          },
        },
      });
      return (res.data || []) as DeviceSummary[];
    },
    refetchInterval: 15000,
  });

  // Approve device mutation
  const approveMutation = useMutation({
    mutationFn: async (deviceId: string) => {
      await api.POST(`/v1/admin/devices/{device_id}/approve`, {
        params: { path: { device_id: deviceId } },
      });
    },
    onSuccess: () => {
      toast.success("Device approved");
      queryClient.invalidateQueries({ queryKey: ["admin", "devices"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to approve device", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  // Suspend device mutation
  const suspendMutation = useMutation({
    mutationFn: async (deviceId: string) => {
      await api.POST(`/v1/admin/devices/{device_id}/suspend`, {
        params: { path: { device_id: deviceId } },
        body: {},
      });
    },
    onSuccess: () => {
      toast.success("Device suspended");
      queryClient.invalidateQueries({ queryKey: ["admin", "devices"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to suspend device", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  // Resume device mutation
  const resumeMutation = useMutation({
    mutationFn: async (deviceId: string) => {
      await api.POST(`/v1/admin/devices/{device_id}/resume`, {
        params: { path: { device_id: deviceId } },
      });
    },
    onSuccess: () => {
      toast.success("Device resumed");
      queryClient.invalidateQueries({ queryKey: ["admin", "devices"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to resume device", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  // Revoke device mutation
  const revokeMutation = useMutation({
    mutationFn: async ({ deviceId, reason }: { deviceId: string; reason: string }) => {
      await api.POST(`/v1/admin/devices/{device_id}/revoke`, {
        params: { path: { device_id: deviceId } },
        body: { reason },
      });
    },
    onSuccess: () => {
      toast.success("Device permanently revoked (0 ms delay)");
      queryClient.invalidateQueries({ queryKey: ["admin", "devices"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to revoke device", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  const allDevices: DeviceSummary[] = Array.isArray(data) ? data : [];
  const filteredDevices = allDevices.filter((d: DeviceSummary) => {
    if (searchName.trim()) {
      return (
        d.name.toLowerCase().includes(searchName.trim().toLowerCase()) ||
        d.id.toLowerCase().includes(searchName.trim().toLowerCase())
      );
    }
    return true;
  });

  const total = filteredDevices.length;
  const totalPages = Math.ceil(total / pageSize) || 1;
  const devices = filteredDevices.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Edge Device Network"
        description="Monitor, approve, configure, and revoke edge recognition terminals across facilities."
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
            {canAddDevice && (
              <Button size="sm" onClick={() => setIsAddWizardOpen(true)}>
                <Plus className="h-4 w-4 mr-1" />
                Add Device
              </Button>
            )}
          </div>
        }
      />

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by device name..."
              value={searchName}
              onChange={(e) => {
                setSearchName(e.target.value);
                setPage(1);
              }}
              className="pl-9 h-9"
            />
          </div>

          <div className="flex items-center gap-1.5">
            <Filter className="h-4 w-4 text-muted-foreground hidden sm:inline" />
            <select
              value={stateFilter}
              onChange={(e) => {
                setStateFilter(e.target.value);
                setPage(1);
              }}
              className="h-9 rounded-md border border-input bg-transparent px-3 py-1 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="all">All States</option>
              <option value="active">Active Only</option>
              <option value="pending">Pending</option>
              <option value="suspended">Suspended</option>
              <option value="revoked">Revoked</option>
            </select>
          </div>
        </div>

        <div className="text-xs text-muted-foreground self-end sm:self-center">
          Showing <span className="font-semibold text-foreground">{devices.length}</span> of{" "}
          <span className="font-semibold text-foreground">{total}</span> devices
        </div>
      </div>

      {/* Table Section */}
      <div className="rounded-lg border bg-card shadow-sm">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Device</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Scopes</TableHead>
              <TableHead>Version</TableHead>
              <TableHead>Network IP</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell><Skeleton className="h-5 w-36" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-24" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-20" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-16" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-24" /></TableCell>
                  <TableCell className="text-right"><Skeleton className="h-8 w-8 ml-auto" /></TableCell>
                </TableRow>
              ))
            ) : devices.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                  <div className="flex flex-col items-center justify-center space-y-2">
                    <Camera className="h-8 w-8 text-muted-foreground/50" />
                    <p className="text-sm font-medium">No edge devices found</p>
                    <p className="text-xs text-muted-foreground">
                      {searchName || stateFilter !== "all"
                        ? "Try adjusting your search criteria or state filter."
                        : "Click 'Add Device' above to pair your first edge camera terminal."}
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              devices.map((device) => (
                <TableRow key={device.id}>
                  <TableCell>
                    <div className="font-medium text-foreground">
                      <Link
                        to={`/devices/${device.id}`}
                        className="hover:underline hover:text-primary transition-colors flex items-center gap-1.5"
                      >
                        {device.name}
                      </Link>
                    </div>
                    <div className="font-mono text-[10px] text-muted-foreground truncate max-w-[200px]">
                      {device.id}
                    </div>
                  </TableCell>
                  <TableCell>
                    <DeviceStatusBadge state={device.state} lastSeen={device.last_seen} />
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {device.scopes && device.scopes.length > 0 ? (
                        device.scopes.map((s: string) => (
                          <Badge key={s} variant="outline" className="text-[10px] px-1 py-0">
                            {s}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">None</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {device.software_version || "client-v0.1.0"}
                  </TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {device.ip_address || "127.0.0.1"}
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
                          <Link to={`/devices/${device.id}`} className="flex items-center gap-2 cursor-pointer">
                            <Eye className="h-4 w-4" />
                            <span>View Details</span>
                          </Link>
                        </DropdownMenuItem>

                        {device.state === "pending" && canApprove && (
                          <DropdownMenuItem
                            onClick={() => approveMutation.mutate(device.id)}
                            className="flex items-center gap-2 cursor-pointer text-emerald-600 focus:text-emerald-600"
                          >
                            <CheckCircle className="h-4 w-4" />
                            <span>Approve Device</span>
                          </DropdownMenuItem>
                        )}

                        {device.state === "active" && canRevoke && (
                          <DropdownMenuItem
                            onClick={() => suspendMutation.mutate(device.id)}
                            className="flex items-center gap-2 cursor-pointer text-amber-600 focus:text-amber-600"
                          >
                            <PauseCircle className="h-4 w-4" />
                            <span>Suspend Device</span>
                          </DropdownMenuItem>
                        )}

                        {device.state === "suspended" && canRevoke && (
                          <DropdownMenuItem
                            onClick={() => resumeMutation.mutate(device.id)}
                            className="flex items-center gap-2 cursor-pointer text-emerald-600 focus:text-emerald-600"
                          >
                            <PlayCircle className="h-4 w-4" />
                            <span>Resume Device</span>
                          </DropdownMenuItem>
                        )}

                        {device.state !== "revoked" && canRevoke && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => setDeviceToRevoke({ id: device.id, name: device.name })}
                              className="text-destructive focus:bg-destructive/10 focus:text-destructive flex items-center gap-2 cursor-pointer"
                            >
                              <XCircle className="h-4 w-4" />
                              <span>Revoke Permanently</span>
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

      {/* Add Device Stepper Wizard */}
      <AddDeviceWizard
        open={isAddWizardOpen}
        onOpenChange={setIsAddWizardOpen}
      />

      {/* Revoke Confirmation Dialog */}
      <RevokeDeviceDialog
        open={deviceToRevoke !== null}
        onOpenChange={(open) => !open && setDeviceToRevoke(null)}
        device={deviceToRevoke}
        onConfirm={async (id, reason) => {
          await revokeMutation.mutateAsync({ deviceId: id, reason });
        }}
        isLoading={revokeMutation.isPending}
      />
    </div>
  );
};
