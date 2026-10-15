// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowLeft, Download, RefreshCw, Sparkles, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import type { UserSummary } from "@/api/models";

export const ReEnrollReport: React.FC = () => {
  // Query migration report from backend
  const { data: report, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["model", "migration-report"],
    queryFn: async () => {
      const res = await api.GET("/v1/model/migration-report");
      return res.data;
    },
  });

  // Query system status to determine active version
  const { data: statusData } = useQuery({
    queryKey: ["admin", "system", "status"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/system/status");
      return res.data;
    },
  });

  // Query all users to extract list of external IDs needing re-enrollment
  const { data: allUsersData } = useQuery<UserSummary[]>({
    queryKey: ["admin", "users", "all"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/users", {
        params: { query: { limit: 500 } },
      });
      return (res.data || []) as unknown as UserSummary[];
    },
  });

  const activeModel = report?.active_model_version || statusData?.model_version || "partialface_ir18_v1";
  const users: UserSummary[] = allUsersData || [];
  const outdatedUsers = users.filter((u: UserSummary) => u.model_version && u.model_version !== activeModel);

  const handleExportCsv = () => {
    if (outdatedUsers.length === 0) {
      toast.info("No outdated user identities to export");
      return;
    }

    const header = "user_id,external_id,current_model_version,enrolled_at\n";
    const rows = outdatedUsers
      .map(
        (u: UserSummary) =>
          `"${u.id}","${u.external_id}","${u.model_version || ""}","${u.created_at || ""}"`
      )
      .join("\n");

    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `freqid_re_enrollment_needed_${activeModel}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    toast.success("Re-enrollment CSV exported successfully");
  };

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
        title="Model Version & Re-Enrollment Report"
        description="Monitor biometric template version distribution and schedule re-captures following neural network upgrades."
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
            <Button
              size="sm"
              onClick={handleExportCsv}
              disabled={outdatedUsers.length === 0}
              className="flex items-center gap-1.5"
            >
              <Download className="h-4 w-4" />
              <span>Export Outdated List (CSV)</span>
            </Button>
          </div>
        }
      />

      {/* Summary Metrics */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active Model Backbone</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold font-mono text-primary">{activeModel}</div>
            <p className="text-xs text-muted-foreground mt-1">Current ONNX inference engine</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Enrolled Templates</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-7 w-20" />
            ) : (
              <div className="text-xl font-bold">{users.length}</div>
            )}
            <p className="text-xs text-muted-foreground mt-1">Persisted in PostgreSQL database</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Re-Enrollment Needed</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-7 w-20" />
            ) : (
              <div
                className={`text-xl font-bold ${
                  outdatedUsers.length > 0
                    ? "text-amber-600 dark:text-amber-400"
                    : "text-emerald-600 dark:text-emerald-400"
                }`}
              >
                {outdatedUsers.length}
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-1">
              {outdatedUsers.length > 0
                ? "Templates created under older neural weights"
                : "All templates match current model backbone"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Outdated Users Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-amber-500" />
            <span>Identities Requiring Model Re-Capture</span>
          </CardTitle>
          <CardDescription>
            These subjects were enrolled using prior model versions. Use the CSV export button above to schedule re-enrollment sessions.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {outdatedUsers.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground flex flex-col items-center justify-center space-y-2">
              <CheckCircle2 className="h-8 w-8 text-emerald-500" />
              <p className="font-medium text-foreground">All User Templates Are Up to Date!</p>
              <p className="text-xs">Every enrolled subject is using the active {activeModel} neural weights.</p>
            </div>
          ) : (
            <div className="divide-y divide-border text-xs">
              {outdatedUsers.map((u) => (
                <div key={u.id} className="py-2.5 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Link
                      to={`/users/${u.id}`}
                      className="font-mono font-medium text-foreground hover:underline hover:text-primary"
                    >
                      {u.external_id}
                    </Link>
                    <p className="text-muted-foreground font-mono text-[10px]">UUID: {u.id}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="warning" className="font-mono text-[10px]">
                      {u.model_version}
                    </Badge>
                    <span className="text-muted-foreground">→</span>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      Needs {activeModel}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
