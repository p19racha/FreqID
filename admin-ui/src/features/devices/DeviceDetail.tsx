// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useCan } from "@/auth/useCan";
import { PERMISSIONS } from "@/auth/permissions";
import { PageHeader } from "@/components/layout/PageHeader";
import { DeviceStatusBadge } from "./DeviceStatusBadge";
import { RevokeDeviceDialog } from "./RevokeDeviceDialog";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowLeft,
  Key,
  ShieldAlert,
  Copy,
  Check,
  PauseCircle,
  PlayCircle,
  XCircle,
  Activity,
  AlertTriangle,
} from "lucide-react";
import { formatExactTimestamp, formatRelativeTime } from "@/lib/formatters";
import { toast } from "sonner";
import type { AuditEventItem } from "@/api/models";

export const DeviceDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [copiedKey, setCopiedKey] = useState(false);
  const [showRevokeDialog, setShowRevokeDialog] = useState(false);

  const canRevoke = useCan(PERMISSIONS.DEVICE_REVOKE);

  const { data: device, isLoading } = useQuery({
    queryKey: ["admin", "device", id],
    queryFn: async () => {
      if (!id) throw new Error("Device ID required");
      const res = await api.GET("/v1/admin/devices/{device_id}", {
        params: { path: { device_id: id } },
      });
      return res.data;
    },
    enabled: Boolean(id),
    refetchInterval: 15000,
  });

  const { data: deviceAudit } = useQuery({
    queryKey: ["admin", "audit", "device", id],
    queryFn: async () => {
      if (!id) return null;
      const res = await api.GET("/v1/admin/audit", {
        params: { query: { device_id: id, limit: 10 } },
      });
      return res.data;
    },
    enabled: Boolean(id),
  });

  // Suspend mutation
  const suspendMutation = useMutation({
    mutationFn: async () => {
      if (!id) return;
      await api.POST("/v1/admin/devices/{device_id}/suspend", {
        params: { path: { device_id: id } },
        body: {},
      });
    },
    onSuccess: () => {
      toast.success("Device suspended");
      queryClient.invalidateQueries({ queryKey: ["admin", "device", id] });
    },
  });

  // Resume mutation
  const resumeMutation = useMutation({
    mutationFn: async () => {
      if (!id) return;
      await api.POST("/v1/admin/devices/{device_id}/resume", {
        params: { path: { device_id: id } },
      });
    },
    onSuccess: () => {
      toast.success("Device resumed");
      queryClient.invalidateQueries({ queryKey: ["admin", "device", id] });
    },
  });

  // Revoke mutation
  const revokeMutation = useMutation({
    mutationFn: async (reason: string) => {
      if (!id) return;
      await api.POST("/v1/admin/devices/{device_id}/revoke", {
        params: { path: { device_id: id } },
        body: { reason },
      });
    },
    onSuccess: () => {
      toast.success("Device permanently revoked");
      queryClient.invalidateQueries({ queryKey: ["admin", "device", id] });
    },
  });

  const copyPublicKey = () => {
    if (!device?.public_key) return;
    navigator.clipboard.writeText(device.public_key);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  };

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

  if (!device) {
    return (
      <div className="space-y-4 text-center py-12">
        <AlertTriangle className="h-10 w-10 text-muted-foreground mx-auto" />
        <h2 className="text-lg font-semibold">Device Not Found</h2>
        <p className="text-sm text-muted-foreground">The requested edge device could not be located.</p>
        <Button variant="outline" onClick={() => navigate("/devices")}>
          Return to Device Fleet
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/devices" className="flex items-center gap-1 text-muted-foreground">
            <ArrowLeft className="h-4 w-4" />
            <span>Back to Fleet</span>
          </Link>
        </Button>
      </div>

      <PageHeader
        title={device.name}
        description={`Registered edge terminal ID: ${device.id}`}
        actions={
          <div className="flex items-center gap-2">
            {device.state === "active" && canRevoke && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => suspendMutation.mutate()}
                disabled={suspendMutation.isPending}
                className="text-amber-600 border-amber-600/30 hover:bg-amber-500/10"
              >
                <PauseCircle className="h-4 w-4 mr-1.5" />
                Suspend
              </Button>
            )}

            {device.state === "suspended" && canRevoke && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => resumeMutation.mutate()}
                disabled={resumeMutation.isPending}
                className="text-emerald-600 border-emerald-600/30 hover:bg-emerald-500/10"
              >
                <PlayCircle className="h-4 w-4 mr-1.5" />
                Resume
              </Button>
            )}

            {device.state !== "revoked" && canRevoke && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setShowRevokeDialog(true)}
              >
                <XCircle className="h-4 w-4 mr-1.5" />
                Revoke Permanently
              </Button>
            )}
          </div>
        }
      />

      {/* Revocation Alert Banner if revoked */}
      {device.state === "revoked" && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive flex items-start gap-3">
          <ShieldAlert className="h-5 w-5 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="font-semibold">Device Permanently Revoked</h4>
            <p className="text-xs text-muted-foreground leading-relaxed">
              This terminal has been permanently revoked by an administrator. Its public key is blacklisted,
              and all per-request signed headers will be rejected with HTTP 401 DEVICE_REVOKED. This state cannot
              be resumed; the physical hardware must be re-paired with a fresh token.
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {/* Device Metadata Card */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Device Information</CardTitle>
            <CardDescription>Network identity and configuration parameters</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Lifecycle State</span>
              <DeviceStatusBadge state={device.state} lastSeen={device.last_seen} />
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Device Scopes</span>
              <div className="flex gap-1">
                {device.scopes && device.scopes.length > 0 ? (
                  device.scopes.map((s: string) => (
                    <Badge key={s} variant="outline" className="text-xs">
                      {s}
                    </Badge>
                  ))
                ) : (
                  <span className="text-muted-foreground">None</span>
                )}
              </div>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Software Version</span>
              <span className="font-mono">{device.software_version || "client-v0.1.0"}</span>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">Network IP Address</span>
              <span className="font-mono">{String(device.recent_heartbeats?.[0]?.ip_address || "127.0.0.1")}</span>
            </div>

            <div className="flex justify-between py-1.5 border-b">
              <span className="text-muted-foreground">First Registered</span>
              <span>{formatExactTimestamp(device.created_at)}</span>
            </div>

            <div className="flex justify-between py-1.5">
              <span className="text-muted-foreground">Last Heartbeat</span>
              <span>
                {formatRelativeTime(device.last_seen)} ({formatExactTimestamp(device.last_seen)})
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Cryptographic Key Information */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Key className="h-4 w-4 text-primary" />
              <span>Ed25519 Public Key</span>
            </CardTitle>
            <CardDescription>
              Public key used by server to verify signed HTTP requests
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Public Key (PEM format)</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={copyPublicKey}
                  className="h-6 text-xs px-2"
                >
                  {copiedKey ? <Check className="h-3 w-3 text-emerald-500 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
                  {copiedKey ? "Copied" : "Copy PEM"}
                </Button>
              </div>
              <pre className="rounded-lg bg-muted p-3 font-mono text-[11px] text-foreground overflow-x-auto whitespace-pre select-all">
                {device.public_key || "Public key not available"}
              </pre>
            </div>

            <div className="rounded-md border p-3 text-xs text-muted-foreground bg-muted/30 space-y-1">
              <p className="font-medium text-foreground">Asymmetric Signing Invariant:</p>
              <p>• The matching private key resides solely on the edge hardware in POSIX 0600 mode.</p>
              <p>• The server never holds or receives the private key.</p>
              <p>• Nonce deduplication and timestamp sliding windows protect against replays.</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent Device Activity / Audit History */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <span>Recent Device Audit Events</span>
          </CardTitle>
          <CardDescription>
            Chronological audit log entries originating from this edge terminal
          </CardDescription>
        </CardHeader>
        <CardContent>
          {deviceAudit?.items && deviceAudit.items.length > 0 ? (
            <div className="divide-y divide-border text-xs">
              {(deviceAudit.items as unknown as AuditEventItem[]).map((ev) => (
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
              No audit records currently found for this device.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Revoke Dialog */}
      <RevokeDeviceDialog
        open={showRevokeDialog}
        onOpenChange={setShowRevokeDialog}
        device={{ id: device.id, name: device.name }}
        onConfirm={async (_, reason) => {
          await revokeMutation.mutateAsync(reason);
        }}
        isLoading={revokeMutation.isPending}
      />
    </div>
  );
};
