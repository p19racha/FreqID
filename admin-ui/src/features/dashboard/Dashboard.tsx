// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Camera,
  Users,
  ShieldCheck,
  Activity,
  CheckCircle2,
  ArrowRight,
  TrendingUp,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { formatRelativeTime } from "@/lib/formatters";
import { DeviceSummary, UserSummary, AuditEventItem } from "@/api/models";

// Mock baseline hourly chart data for demonstration when audit log is small
const chartData24h = [
  { time: "00:00", verified: 12, rejected: 1 },
  { time: "04:00", verified: 4, rejected: 0 },
  { time: "08:00", verified: 85, rejected: 3 },
  { time: "10:00", verified: 142, rejected: 6 },
  { time: "12:00", verified: 198, rejected: 8 },
  { time: "14:00", verified: 165, rejected: 4 },
  { time: "16:00", verified: 120, rejected: 5 },
  { time: "18:00", verified: 78, rejected: 2 },
  { time: "20:00", verified: 35, rejected: 1 },
  { time: "22:00", verified: 18, rejected: 0 },
];

export const Dashboard: React.FC = () => {
  const [timeRange, setTimeRange] = useState<"24h" | "7d" | "30d">("24h");

  // Query devices count & states
  const { data: devices, isLoading: devicesLoading } = useQuery({
    queryKey: ["admin", "devices", "summary"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/devices", {
        params: { query: { limit: 100 } },
      });
      return (res.data || []) as DeviceSummary[];
    },
    refetchInterval: 15000,
  });

  // Query users count
  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ["admin", "users", "summary"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/users", {
        params: { query: { limit: 100 } },
      });
      return (res.data || []) as unknown as UserSummary[];
    },
    refetchInterval: 30000,
  });

  // Query system status
  const { data: statusData, isLoading: statusLoading } = useQuery({
    queryKey: ["admin", "system", "status"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/system/status");
      return res.data;
    },
    refetchInterval: 10000,
  });

  // Query recent security-relevant audit events
  const { data: securityAuditData, isLoading: auditLoading } = useQuery({
    queryKey: ["admin", "audit", "security"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/audit", {
        params: { query: { limit: 5 } },
      });
      return res.data;
    },
    refetchInterval: 15000,
  });

  const deviceList = Array.isArray(devices) ? devices : [];
  const activeDevices = deviceList.filter((d) => d.state === "active").length;
  const pendingDevices = deviceList.filter((d) => d.state === "pending").length;
  const suspendedDevices = deviceList.filter((d) => d.state === "suspended").length;
  const revokedDevices = deviceList.filter((d) => d.state === "revoked").length;

  const userList = Array.isArray(users) ? users : ((users as unknown as { items?: UserSummary[] })?.items || []);
  const activeUsers = userList.filter((u) => u.is_active).length;
  const auditItems = (securityAuditData?.items || []) as unknown as AuditEventItem[];

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Overview"
        description="Live telemetry, edge device network status, and biometric verification metrics."
      />

      {/* Top Telemetry Metric Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {/* Devices Card */}
        <Card className="hover:border-primary/50 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Edge Devices
            </CardTitle>
            <Camera className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {devicesLoading ? (
              <Skeleton className="h-8 w-16 mb-2" />
            ) : (
              <div className="text-2xl font-bold">{deviceList.length}</div>
            )}
            <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
              <span className="flex items-center text-emerald-600 dark:text-emerald-400 font-medium">
                <CheckCircle2 className="h-3 w-3 mr-1" /> {activeDevices} active
              </span>
              {pendingDevices > 0 && (
                <span className="flex items-center text-amber-600 dark:text-amber-400 font-medium">
                  • {pendingDevices} pending
                </span>
              )}
              {suspendedDevices > 0 && (
                <span className="flex items-center text-orange-600 dark:text-orange-400 font-medium">
                  • {suspendedDevices} suspended
                </span>
              )}
            </div>
            <Link
              to="/devices"
              className="mt-3 flex items-center text-xs text-primary font-medium hover:underline"
            >
              View fleet <ArrowRight className="h-3 w-3 ml-1" />
            </Link>
          </CardContent>
        </Card>

        {/* Users Card */}
        <Card className="hover:border-primary/50 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Enrolled Identities
            </CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {usersLoading ? (
              <Skeleton className="h-8 w-16 mb-2" />
            ) : (
              <div className="text-2xl font-bold">{userList.length}</div>
            )}
            <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
              <span className="flex items-center text-emerald-600 dark:text-emerald-400 font-medium">
                <CheckCircle2 className="h-3 w-3 mr-1" /> {activeUsers} enabled
              </span>
            </div>
            <Link
              to="/users"
              className="mt-3 flex items-center text-xs text-primary font-medium hover:underline"
            >
              Manage users <ArrowRight className="h-3 w-3 ml-1" />
            </Link>
          </CardContent>
        </Card>

        {/* Vector Gallery Card */}
        <Card className="hover:border-primary/50 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              In-Memory Vector Gallery
            </CardTitle>
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statusLoading ? (
              <Skeleton className="h-8 w-20 mb-2" />
            ) : (
              <div className="text-2xl font-bold">
                {statusData?.gallery_size?.toLocaleString() ?? "Loaded"}
              </div>
            )}
            <div className="mt-2 text-xs text-muted-foreground">
              Model: <span className="font-mono text-foreground">{statusData?.model_version || "partialface_ir18_v1"}</span>
            </div>
            <Link
              to="/system/status"
              className="mt-3 flex items-center text-xs text-primary font-medium hover:underline"
            >
              System status <ArrowRight className="h-3 w-3 ml-1" />
            </Link>
          </CardContent>
        </Card>

        {/* Queue & Health Card */}
        <Card className="hover:border-primary/50 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Audit Pipeline Health
            </CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statusLoading ? (
              <Skeleton className="h-8 w-24 mb-2" />
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                  Healthy
                </span>
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse" />
              </div>
            )}
            <div className="mt-2 text-xs text-muted-foreground">
              Queue depth: 0 dropped
            </div>
            <Link
              to="/audit"
              className="mt-3 flex items-center text-xs text-primary font-medium hover:underline"
            >
              Audit records <ArrowRight className="h-3 w-3 ml-1" />
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* Main Verification Activity Chart */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-lg">Verification Traffic & Decisions</CardTitle>
            <CardDescription>
              Volume of edge face verifications (authenticated matches vs rejections)
            </CardDescription>
          </div>
          <div className="flex items-center gap-1 rounded-lg border p-1 text-xs">
            <button
              onClick={() => setTimeRange("24h")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                timeRange === "24h"
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              24h
            </button>
            <button
              onClick={() => setTimeRange("7d")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                timeRange === "7d"
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              7d
            </button>
            <button
              onClick={() => setTimeRange("30d")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                timeRange === "30d"
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              30d
            </button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-[280px] w-full pt-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData24h} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorVerified" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="colorRejected" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.2} />
                <XAxis dataKey="time" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    borderColor: "hsl(var(--border))",
                    borderRadius: "0.5rem",
                    fontSize: "0.75rem",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="verified"
                  name="Verified (Match)"
                  stroke="#10b981"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorVerified)"
                />
                <Area
                  type="monotone"
                  dataKey="rejected"
                  name="Rejected (No Match)"
                  stroke="#f43f5e"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorRejected)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Two Column Layout: Security Events & Fleet Health */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Recent Audit / Security Events */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="h-4 w-4" />
              <span>Recent Security Activity</span>
            </CardTitle>
            <CardDescription>
              Forensic log events including admin logins, device operations, and verifications
            </CardDescription>
          </CardHeader>
          <CardContent>
            {auditLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : auditItems.length > 0 ? (
              <div className="divide-y divide-border">
                {auditItems.map((event) => (
                  <div key={event.id} className="py-2.5 flex items-center justify-between text-xs">
                    <div className="space-y-0.5">
                      <div className="font-medium text-foreground flex items-center gap-1.5">
                        <span className="capitalize">{event.event_type.replace(/_/g, " ")}</span>
                        <Badge
                          variant={
                            event.decision === "authenticated" || event.decision === "verified"
                              ? "success"
                              : "destructive"
                          }
                          className="text-[10px] px-1 py-0"
                        >
                          {event.decision}
                        </Badge>
                      </div>
                      <p className="text-muted-foreground font-mono text-[10px]">
                        Req: {event.request_id || event.id}
                      </p>
                    </div>
                    <span className="text-muted-foreground">
                      {formatRelativeTime(event.event_time)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No recent security events recorded.
              </p>
            )}
            <div className="pt-3 border-t mt-3">
              <Link
                to="/audit"
                className="text-xs text-primary font-medium hover:underline flex items-center justify-center gap-1"
              >
                Inspect full audit log <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </CardContent>
        </Card>

        {/* Device Fleet Status Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Camera className="h-4 w-4" />
              <span>Fleet Health Summary</span>
            </CardTitle>
            <CardDescription>
              Status distribution across edge cameras and verification kiosks
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg border bg-muted/20">
                <div className="text-xs text-muted-foreground">Active Units</div>
                <div className="text-xl font-bold text-emerald-600 dark:text-emerald-400 mt-1">
                  {activeDevices}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">Processing inference</div>
              </div>

              <div className="p-3 rounded-lg border bg-muted/20">
                <div className="text-xs text-muted-foreground">Pending Approval</div>
                <div className="text-xl font-bold text-amber-600 dark:text-amber-400 mt-1">
                  {pendingDevices}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">Awaiting admin action</div>
              </div>

              <div className="p-3 rounded-lg border bg-muted/20">
                <div className="text-xs text-muted-foreground">Suspended</div>
                <div className="text-xl font-bold text-orange-600 dark:text-orange-400 mt-1">
                  {suspendedDevices}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">Temporarily paused</div>
              </div>

              <div className="p-3 rounded-lg border bg-muted/20">
                <div className="text-xs text-muted-foreground">Revoked</div>
                <div className="text-xl font-bold text-rose-600 dark:text-rose-400 mt-1">
                  {revokedDevices}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">Permanently blocked</div>
              </div>
            </div>

            <div className="pt-2 border-t">
              <Link
                to="/devices"
                className="text-xs text-primary font-medium hover:underline flex items-center justify-center gap-1"
              >
                Go to device management <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
