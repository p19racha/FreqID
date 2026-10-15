// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import {
  Sliders,
  Shield,
  Clock,
  AlertTriangle,
  Save,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";

interface SettingsState {
  verify_threshold: number;
  enroll_duplicate_threshold: number;
  enroll_duplicate_policy: "block" | "warn";
  lockout_max_failures: number;
  lockout_base_seconds: number;
  audit_retention_days: number;
}

const defaultSettings: SettingsState = {
  verify_threshold: 0.35,
  enroll_duplicate_threshold: 0.65,
  enroll_duplicate_policy: "block",
  lockout_max_failures: 5,
  lockout_base_seconds: 900,
  audit_retention_days: 90,
};

export const Settings: React.FC = () => {
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState<SettingsState>(defaultSettings);
  const [isDiffOpen, setIsDiffOpen] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);

  // Query current settings
  const { data: serverSettings, refetch, isFetching } = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: async () => {
      const res = await api.GET("/v1/admin/settings");
      return (res.data || {}) as Partial<SettingsState>;
    },
  });

  // Sync server settings into local form state once loaded
  React.useEffect(() => {
    if (serverSettings && !isInitialized) {
      setFormData({
        verify_threshold: serverSettings.verify_threshold ?? defaultSettings.verify_threshold,
        enroll_duplicate_threshold:
          serverSettings.enroll_duplicate_threshold ?? defaultSettings.enroll_duplicate_threshold,
        enroll_duplicate_policy:
          serverSettings.enroll_duplicate_policy ?? defaultSettings.enroll_duplicate_policy,
        lockout_max_failures:
          serverSettings.lockout_max_failures ?? defaultSettings.lockout_max_failures,
        lockout_base_seconds:
          serverSettings.lockout_base_seconds ?? defaultSettings.lockout_base_seconds,
        audit_retention_days:
          serverSettings.audit_retention_days ?? defaultSettings.audit_retention_days,
      });
      setIsInitialized(true);
    }
  }, [serverSettings, isInitialized]);

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: async (updated: SettingsState) => {
      await api.PUT("/v1/admin/settings", {
        body: {
          settings: updated as unknown as Record<string, unknown>,
        },
      });
    },
    onSuccess: () => {
      toast.success("System configuration updated successfully");
      setIsDiffOpen(false);
      queryClient.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
    onError: (err: unknown) => {
      toast.error("Failed to update settings", {
        description: err instanceof Error ? err.message : "Error",
      });
    },
  });

  const handleSaveClick = (e: React.FormEvent) => {
    e.preventDefault();
    setIsDiffOpen(true);
  };

  const getChangedFields = () => {
    const changes: { name: string; oldVal: string; newVal: string; warning?: string }[] = [];
    const base = serverSettings || defaultSettings;

    if (formData.verify_threshold !== base.verify_threshold) {
      const isLower = formData.verify_threshold < (base.verify_threshold ?? 0.35);
      changes.push({
        name: "Verification Cosine Threshold",
        oldVal: String(base.verify_threshold ?? 0.35),
        newVal: String(formData.verify_threshold),
        warning: isLower
          ? "Lowering threshold increases false acceptances (higher risk of impostors passing)."
          : "Raising threshold increases false rejections (valid users may be rejected in poor lighting).",
      });
    }

    if (formData.enroll_duplicate_policy !== base.enroll_duplicate_policy) {
      changes.push({
        name: "Duplicate Enrollment Policy",
        oldVal: String(base.enroll_duplicate_policy ?? "block"),
        newVal: String(formData.enroll_duplicate_policy),
        warning:
          formData.enroll_duplicate_policy === "warn"
            ? "Permitting duplicate biometric identities allows the same person to hold multiple IDs."
            : undefined,
      });
    }

    if (formData.lockout_max_failures !== base.lockout_max_failures) {
      changes.push({
        name: "Lockout Failed Login Threshold",
        oldVal: String(base.lockout_max_failures ?? 5),
        newVal: String(formData.lockout_max_failures),
      });
    }

    if (formData.audit_retention_days !== base.audit_retention_days) {
      changes.push({
        name: "Audit Log Retention Schedule",
        oldVal: `${base.audit_retention_days ?? 90} days`,
        newVal: `${formData.audit_retention_days} days`,
        warning:
          formData.audit_retention_days < (base.audit_retention_days ?? 90)
            ? "Decreasing retention schedule permanently deletes older audit records on the next pruning cycle."
            : undefined,
      });
    }

    return changes;
  };

  const changes = getChangedFields();

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Parameters & Governance"
        description="Owner-level configuration of biometric matching strictness, security lockout rules, and retention schedules."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setIsInitialized(false);
              refetch();
            }}
            disabled={isFetching}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} />
            Reset to Server
          </Button>
        }
      />

      <form onSubmit={handleSaveClick} className="space-y-6">
        {/* Biometric Verification Thresholds */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Sliders className="h-4 w-4 text-primary" />
              <span>Biometric Matching & Cosine Cutoffs</span>
            </CardTitle>
            <CardDescription>
              Control the sensitivity of 1:1 verification and duplicate candidate screening
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="verify-threshold">1:1 Verification Threshold</Label>
                <Input
                  id="verify-threshold"
                  type="number"
                  step="0.01"
                  min="0.10"
                  max="0.90"
                  value={formData.verify_threshold}
                  onChange={(e) =>
                    setFormData({ ...formData, verify_threshold: parseFloat(e.target.value) })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Default: <code className="font-mono">0.35</code>. Normalized angular cosine distance.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="dup-threshold">Duplicate Screening Threshold</Label>
                <Input
                  id="dup-threshold"
                  type="number"
                  step="0.01"
                  min="0.30"
                  max="0.95"
                  value={formData.enroll_duplicate_threshold}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      enroll_duplicate_threshold: parseFloat(e.target.value),
                    })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Default: <code className="font-mono">0.65</code>. Flag matches during enrollment.
                </p>
              </div>
            </div>

            <div className="space-y-2 pt-2 border-t">
              <Label htmlFor="dup-policy">Duplicate Enrollment Conflict Policy</Label>
              <select
                id="dup-policy"
                className="w-full sm:w-72 rounded-md border border-input bg-transparent px-3 py-2 text-sm text-foreground shadow-sm"
                value={formData.enroll_duplicate_policy}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    enroll_duplicate_policy: e.target.value as "block" | "warn",
                  })
                }
              >
                <option value="block">Block Duplicate (HTTP 409 Conflict)</option>
                <option value="warn">Warn & Allow (Log audit alert)</option>
              </select>
              <p className="text-xs text-muted-foreground">
                Determines server response if an enrolled face matches an existing identity in the gallery.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Security & Lockouts */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Shield className="h-4 w-4 text-primary" />
              <span>Anti-Brute Force & Account Lockouts</span>
            </CardTitle>
            <CardDescription>
              Progressive exponential lockout rules for administrator credentials and edge requests
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="max-failures">Consecutive Failed Logins Before Lockout</Label>
                <Input
                  id="max-failures"
                  type="number"
                  min="3"
                  max="20"
                  value={formData.lockout_max_failures}
                  onChange={(e) =>
                    setFormData({ ...formData, lockout_max_failures: parseInt(e.target.value) })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Default: <code className="font-mono">5</code> failed attempts.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="base-lockout">Base Lockout Duration (Seconds)</Label>
                <Input
                  id="base-lockout"
                  type="number"
                  step="60"
                  min="60"
                  max="7200"
                  value={formData.lockout_base_seconds}
                  onChange={(e) =>
                    setFormData({ ...formData, lockout_base_seconds: parseInt(e.target.value) })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Default: <code className="font-mono">900</code>s (15 minutes). Doubles progressively.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Compliance & Data Retention */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Clock className="h-4 w-4 text-primary" />
              <span>GDPR Data Minimization & Audit Retention</span>
            </CardTitle>
            <CardDescription>
              Automatic purge schedule for historical audit events and pairing tokens
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="retention-days">Audit Event Retention (Days)</Label>
              <Input
                id="retention-days"
                type="number"
                min="30"
                max="730"
                className="sm:w-72"
                value={formData.audit_retention_days}
                onChange={(e) =>
                  setFormData({ ...formData, audit_retention_days: parseInt(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">
                Events older than this period are purged by the <code className="font-mono">audit_retention.py</code>{" "}
                cron job using the restricted <code className="font-mono">freqid_maint</code> database role.
              </p>
            </div>
          </CardContent>

          <CardFooter className="flex justify-between border-t pt-4">
            <span className="text-xs text-muted-foreground">
              Settings apply dynamically across the cluster upon commit.
            </span>
            <Button type="submit" disabled={updateMutation.isPending}>
              <Save className="h-4 w-4 mr-1.5" />
              Save Configuration
            </Button>
          </CardFooter>
        </Card>
      </form>

      {/* Confirmation Diff Dialog for Risky Parameter Changes */}
      <AlertDialog open={isDiffOpen} onOpenChange={setIsDiffOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <div className="flex items-center gap-2 text-primary">
              <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0" />
              <AlertDialogTitle>Confirm System Parameter Modifications</AlertDialogTitle>
            </div>
            <AlertDialogDescription className="space-y-3 pt-2 text-left">
              {changes.length === 0 ? (
                <p>No configuration values have been modified.</p>
              ) : (
                <div className="space-y-3">
                  <p className="text-xs text-muted-foreground">
                    Please review the impact of your modifications:
                  </p>
                  <div className="space-y-2">
                    {changes.map((c, i) => (
                      <div key={i} className="p-2.5 rounded-lg border bg-muted/40 text-xs space-y-1">
                        <div className="font-semibold text-foreground">{c.name}</div>
                        <div className="flex items-center gap-2 text-muted-foreground font-mono">
                          <span>{c.oldVal}</span>
                          <span>→</span>
                          <span className="font-bold text-primary">{c.newVal}</span>
                        </div>
                        {c.warning && (
                          <div className="text-[11px] text-amber-600 dark:text-amber-400 font-medium pt-0.5">
                            ⚠️ {c.warning}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>

          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={changes.length === 0 || updateMutation.isPending}
              onClick={() => updateMutation.mutate(formData)}
            >
              {updateMutation.isPending ? "Applying..." : "Confirm & Apply"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
