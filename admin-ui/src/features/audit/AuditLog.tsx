// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, getApiBaseUrl } from "@/api/client";
import { authStore } from "@/auth/authStore";
import { useCan } from "@/auth/useCan";
import { PERMISSIONS } from "@/auth/permissions";
import { PageHeader } from "@/components/layout/PageHeader";
import { AuditDetailDrawer } from "./AuditDetailDrawer";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  Download,
  Search,
  RefreshCw,
  FileText,
  Eye,
  ShieldAlert,
  Copy,
  Check,
} from "lucide-react";
import { formatRelativeTime, formatExactTimestamp } from "@/lib/formatters";
import { toast } from "sonner";
import type { AuditEventItem } from "@/api/models";

export const AuditLog: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedEvent, setSelectedEvent] = useState<AuditEventItem | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const canExportCsv = useCan(PERMISSIONS.AUDIT_EXPORT_CSV);

  // Read non-sensitive filters from URL query string
  const page = Number(searchParams.get("page")) || 1;
  const pageSize = 20;
  const eventType = searchParams.get("event_type") || "";
  const decision = searchParams.get("decision") || "";
  const requestId = searchParams.get("request_id") || "";

  const updateParam = (key: string, val: string) => {
    const next = new URLSearchParams(searchParams);
    if (val) {
      next.set(key, val);
    } else {
      next.delete(key);
    }
    next.set("page", "1");
    setSearchParams(next);
  };

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["admin", "audit", { page, eventType, decision, requestId }],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/audit", {
        params: {
          query: {
            limit: pageSize,
            event_type: eventType || undefined,
            decision: decision || undefined,
          },
        },
      });
      return res.data;
    },
    refetchInterval: 15000,
  });

  const handleExportCsv = async () => {
    setIsExporting(true);
    toast.info("Preparing audit log CSV export (streaming)...");

    try {
      const baseUrl = getApiBaseUrl();
      const token = authStore.getAccessToken();
      const url = new URL(`${baseUrl}/v1/admin/audit/export`);
      url.searchParams.set("format", "csv");
      if (eventType) url.searchParams.set("event_type", eventType);
      if (decision) url.searchParams.set("decision", decision);

      const res = await fetch(url.toString(), {
        headers: {
          Authorization: token ? `Bearer ${token}` : "",
        },
      });

      if (!res.ok) {
        if (res.status === 400) {
          throw new Error("Export query exceeded maximum row capacity (10,000 rows). Please narrow your filters.");
        }
        throw new Error(`Export failed with HTTP ${res.status}`);
      }

      const blob = await res.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = `freqid_audit_log_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(downloadUrl);
      toast.success("Audit log CSV export completed");
    } catch (err: unknown) {
      toast.error("Export Error", {
        description: err instanceof Error ? err.message : "Failed to stream audit records",
      });
    } finally {
      setIsExporting(false);
    }
  };

  const copyRequestId = (reqId: string) => {
    navigator.clipboard.writeText(reqId);
    setCopiedId(reqId);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const events = (data?.items || []) as unknown as AuditEventItem[];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / pageSize) || 1;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tamper-Evident Audit Trail"
        description="Immutable cryptographic record of authentications, administrative mutations, and face verifications."
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
            {canExportCsv && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleExportCsv}
                disabled={isExporting}
                className="flex items-center gap-1.5"
              >
                <Download className="h-4 w-4" />
                <span>{isExporting ? "Exporting..." : "Export CSV"}</span>
              </Button>
            )}
          </div>
        }
      />

      {/* Quick Filter Chips */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground mr-1">Quick Filters:</span>
        <button
          onClick={() => {
            const next = new URLSearchParams(searchParams);
            next.delete("event_type");
            next.delete("decision");
            next.set("page", "1");
            setSearchParams(next);
          }}
          className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
            !eventType && !decision
              ? "bg-primary text-primary-foreground border-primary"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          All Activity
        </button>

        <button
          onClick={() => {
            const next = new URLSearchParams(searchParams);
            next.set("event_type", "admin_login");
            next.set("decision", "rejected");
            next.set("page", "1");
            setSearchParams(next);
          }}
          className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors flex items-center gap-1 ${
            eventType === "admin_login" && decision === "rejected"
              ? "bg-rose-500 text-white border-rose-500"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          <ShieldAlert className="h-3 w-3" />
          <span>Failed Logins</span>
        </button>

        <button
          onClick={() => {
            const next = new URLSearchParams(searchParams);
            next.set("event_type", "device_revoked");
            next.delete("decision");
            next.set("page", "1");
            setSearchParams(next);
          }}
          className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
            eventType === "device_revoked"
              ? "bg-rose-500 text-white border-rose-500"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          Revocations
        </button>

        <button
          onClick={() => {
            const next = new URLSearchParams(searchParams);
            next.set("event_type", "biometric_verify");
            next.delete("decision");
            next.set("page", "1");
            setSearchParams(next);
          }}
          className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
            eventType === "biometric_verify"
              ? "bg-primary text-primary-foreground border-primary"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          Biometric Verifications
        </button>
      </div>

      {/* Search and Dropdown Filter Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search Request ID..."
              value={requestId}
              onChange={(e) => updateParam("request_id", e.target.value)}
              className="pl-9 h-9"
            />
          </div>

          <select
            value={eventType}
            onChange={(e) => updateParam("event_type", e.target.value)}
            className="h-9 rounded-md border border-input bg-transparent px-3 py-1 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
          >
            <option value="">All Event Types</option>
            <option value="biometric_verify">Biometric Verify</option>
            <option value="biometric_identify">Biometric Identify</option>
            <option value="user_enrolled">User Enrolled</option>
            <option value="device_paired">Device Paired</option>
            <option value="device_revoked">Device Revoked</option>
            <option value="admin_login">Admin Login</option>
          </select>

          <select
            value={decision}
            onChange={(e) => updateParam("decision", e.target.value)}
            className="h-9 rounded-md border border-input bg-transparent px-3 py-1 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
          >
            <option value="">All Decisions</option>
            <option value="verified">Verified</option>
            <option value="authenticated">Authenticated</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>

        <div className="text-xs text-muted-foreground self-end sm:self-center">
          Showing <span className="font-semibold text-foreground">{events.length}</span> of{" "}
          <span className="font-semibold text-foreground">{total}</span> records
        </div>
      </div>

      {/* Table Section */}
      <div className="rounded-lg border bg-card shadow-sm">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Timestamp</TableHead>
              <TableHead>Event</TableHead>
              <TableHead>Decision</TableHead>
              <TableHead>Principal Type</TableHead>
              <TableHead>Correlation ID</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell><Skeleton className="h-5 w-28" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-32" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-20" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-16" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-32" /></TableCell>
                  <TableCell className="text-right"><Skeleton className="h-8 w-16 ml-auto" /></TableCell>
                </TableRow>
              ))
            ) : events.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                  <div className="flex flex-col items-center justify-center space-y-2">
                    <FileText className="h-8 w-8 text-muted-foreground/50" />
                    <p className="text-sm font-medium">No audit events match your search</p>
                    <p className="text-xs text-muted-foreground">
                      Try clearing filters or broadening your search range.
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              events.map((ev) => {
                const isPositive =
                  ev.decision === "verified" || ev.decision === "authenticated" || ev.decision === "allowed";
                return (
                  <TableRow
                    key={ev.id}
                    className={
                      !isPositive
                        ? "bg-destructive/5 hover:bg-destructive/10 transition-colors"
                        : undefined
                    }
                  >
                    <TableCell className="text-xs">
                      <span className="font-medium text-foreground block">
                        {formatRelativeTime(ev.event_time)}
                      </span>
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {formatExactTimestamp(ev.event_time)}
                      </span>
                    </TableCell>

                    <TableCell>
                      <span className="font-semibold text-xs capitalize text-foreground">
                        {ev.event_type.replace(/_/g, " ")}
                      </span>
                    </TableCell>

                    <TableCell>
                      <Badge
                        variant={isPositive ? "success" : "destructive"}
                        className="capitalize text-xs font-medium"
                      >
                        {ev.decision}
                      </Badge>
                    </TableCell>

                    <TableCell className="text-xs capitalize text-muted-foreground">
                      {ev.principal_type}
                    </TableCell>

                    <TableCell>
                      <div className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground max-w-[220px]">
                        <span className="truncate">{ev.request_id || ev.id}</span>
                        {ev.request_id && (
                          <button
                            onClick={() => ev.request_id && copyRequestId(ev.request_id)}
                            className="text-muted-foreground hover:text-foreground shrink-0"
                            title="Copy Request ID"
                          >
                            {copiedId === ev.request_id ? (
                              <Check className="h-3 w-3 text-emerald-500" />
                            ) : (
                              <Copy className="h-3 w-3" />
                            )}
                          </button>
                        )}
                      </div>
                    </TableCell>

                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setSelectedEvent(ev)}
                        className="h-8 text-xs flex items-center gap-1 ml-auto"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        <span>Inspect</span>
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })
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
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("page", String(page - 1));
              setSearchParams(next);
            }}
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
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("page", String(page + 1));
              setSearchParams(next);
            }}
          >
            Next
          </Button>
        </div>
      )}

      {/* Audit Detail Drawer */}
      <AuditDetailDrawer
        open={selectedEvent !== null}
        onOpenChange={(open) => !open && setSelectedEvent(null)}
        event={selectedEvent}
      />
    </div>
  );
};
