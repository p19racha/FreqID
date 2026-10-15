// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { DeviceSummary } from "@/api/models";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Copy,
  Check,
  AlertTriangle,
  Terminal,
  Loader2,
  CheckCircle2,
  KeyRound,
} from "lucide-react";
import { toast } from "sonner";

interface AddDeviceWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const AddDeviceWizard: React.FC<AddDeviceWizardProps> = ({
  open,
  onOpenChange,
}) => {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [deviceName, setDeviceName] = useState("");
  const [scopePreset, setScopePreset] = useState<"verify" | "identify" | "enroll">("verify");
  const [expiresMinutes, setExpiresMinutes] = useState(15);
  const [isLoading, setIsLoading] = useState(false);

  // Single-use token state: strictly local to this modal lifecycle (Hard Rule 4)
  const [pairingToken, setPairingToken] = useState<string | null>(null);
  const [countdownSeconds, setCountdownSeconds] = useState(15 * 60);

  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState(false);

  const queryClient = useQueryClient();

  // Reset all sensitive state when dialog closes
  useEffect(() => {
    if (!open) {
      setStep(1);
      setDeviceName("");
      setPairingToken(null);
      setCopiedToken(false);
      setCopiedCommand(false);
    }
  }, [open]);

  // Countdown timer for pairing token
  useEffect(() => {
    if (step !== 2 || !pairingToken) return;

    const interval = setInterval(() => {
      setCountdownSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          toast.error("Pairing token expired", {
            description: "The single-use pairing token has expired. Please create a new one.",
          });
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [step, pairingToken]);

  // Polling to detect when the device completes pairing handshake
  useEffect(() => {
    if (step !== 2 || !deviceName) return;

    const pollInterval = setInterval(async () => {
      try {
        const res = await api.GET("/v1/admin/devices", {
          params: { query: { limit: 100 } },
        });

        const devices = res.data as DeviceSummary[] | undefined;
        const matched = devices?.find((d) => d.name === deviceName);
        if (matched && (matched.state === "active" || matched.state === "pending")) {
          setStep(3);
          queryClient.invalidateQueries({ queryKey: ["admin", "devices"] });
          clearInterval(pollInterval);
        }
      } catch {
        // Polling errors ignored
      }
    }, 3000);

    return () => clearInterval(pollInterval);
  }, [step, deviceName, queryClient]);

  const handleGenerateToken = async (e: React.FormEvent | React.MouseEvent) => {
    e.preventDefault();
    if (!deviceName.trim()) return;

    setIsLoading(true);
    try {
      const res = await api.POST("/v1/admin/devices/pairing-tokens", {
        body: {
          name_hint: deviceName.trim(),
          scopes: [scopePreset],
          expires_in_minutes: expiresMinutes,
        },
      });

      if (res.data) {
        setPairingToken(res.data.token);
        setCountdownSeconds(expiresMinutes * 60);
        setStep(2);
        toast.success("Single-use pairing token generated");
      }
    } catch (err: unknown) {
      toast.error("Failed to generate pairing token", {
        description: err instanceof Error ? err.message : "Server error",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const serverUrl = window.location.origin;
  const pairCommand = `freqid-client pair --server "${serverUrl}" --token "${pairingToken || "<token>"}" --name "${deviceName}"`;

  const copyToken = () => {
    if (!pairingToken) return;
    navigator.clipboard.writeText(pairingToken);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 2000);
  };

  const copyCommand = () => {
    navigator.clipboard.writeText(pairCommand);
    setCopiedCommand(true);
    setTimeout(() => setCopiedCommand(false), 2000);
  };

  const formatCountdown = (secs: number) => {
    const mins = Math.floor(secs / 60);
    const remainder = secs % 60;
    return `${mins}:${remainder < 10 ? "0" : ""}${remainder}`;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-primary" />
            <span>Add Edge Device (Cryptographic Pairing)</span>
          </DialogTitle>
          <DialogDescription>
            Pair a camera or kiosk hardware terminal using Ed25519 asymmetric cryptography.
          </DialogDescription>
        </DialogHeader>

        {/* STEP 1: Device Configuration */}
        {step === 1 && (
          <form onSubmit={handleGenerateToken} className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="device-name">Device Name / Location *</Label>
              <Input
                id="device-name"
                placeholder="e.g. front-entrance-cam-01"
                required
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                autoFocus
              />
              <p className="text-xs text-muted-foreground">
                A human-readable label identifying where this edge camera or kiosk is deployed.
              </p>
            </div>

            <div className="space-y-2">
              <Label>Device Operational Scopes</Label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 pt-1">
                <div
                  onClick={() => setScopePreset("verify")}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    scopePreset === "verify"
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  <div className="font-semibold text-xs text-foreground">Verify Only</div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    1:1 badge verification. Cannot search gallery.
                  </div>
                </div>

                <div
                  onClick={() => setScopePreset("identify")}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    scopePreset === "identify"
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  <div className="font-semibold text-xs text-foreground">1:N Identify</div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    Searches enrolled gallery without identity claim.
                  </div>
                </div>

                <div
                  onClick={() => setScopePreset("enroll")}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    scopePreset === "enroll"
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  <div className="font-semibold text-xs text-foreground">Enroll Station</div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    Authorized to capture and submit new templates.
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="token-ttl">Token Expiration Time</Label>
              <select
                id="token-ttl"
                className="w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm"
                value={expiresMinutes}
                onChange={(e) => setExpiresMinutes(Number(e.target.value))}
              >
                <option value={15}>15 minutes (Recommended)</option>
                <option value={30}>30 minutes</option>
                <option value={60}>1 hour</option>
              </select>
            </div>

            <DialogFooter className="pt-4">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={isLoading || !deviceName.trim()}
                onClick={handleGenerateToken}
              >
                {isLoading ? "Generating..." : "Generate Pairing Token"}
              </Button>
            </DialogFooter>
          </form>
        )}

        {/* STEP 2: Show Token Once & Waiting for Pairing */}
        {step === 2 && (
          <div className="space-y-4 py-2">
            {/* Warning Banner (Hard Rule 4) */}
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-600 dark:text-amber-400 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Security Notice: </span>
                This pairing token is shown <strong>exactly once</strong>. It will not be stored
                in your browser or displayed again after closing this window.
              </div>
            </div>

            {/* Token Card */}
            <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="font-medium">Single-Use Pairing Token</span>
                <span className="font-mono text-foreground font-semibold">
                  Expires in {formatCountdown(countdownSeconds)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="font-mono text-sm font-semibold tracking-wider bg-background px-3 py-2 rounded border flex-1 select-all truncate">
                  {pairingToken}
                </div>
                <Button variant="outline" size="sm" onClick={copyToken} className="h-9">
                  {copiedToken ? <Check className="h-4 w-4 text-emerald-500 mr-1" /> : <Copy className="h-4 w-4 mr-1" />}
                  {copiedToken ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>

            {/* Terminal Command to Run */}
            <div className="space-y-2">
              <Label className="text-xs">Run this command on the edge camera hardware:</Label>
              <div className="rounded-lg bg-zinc-950 text-zinc-100 p-3 font-mono text-xs flex items-center justify-between gap-2 overflow-x-auto">
                <div className="flex items-center gap-2 truncate">
                  <Terminal className="h-4 w-4 shrink-0 text-emerald-400" />
                  <span className="truncate">{pairCommand}</span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={copyCommand}
                  className="h-7 text-xs text-zinc-300 hover:text-white shrink-0"
                >
                  {copiedCommand ? <Check className="h-3 w-3 text-emerald-400 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
                  {copiedCommand ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>

            {/* Live Waiting Animation */}
            <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 flex items-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <div className="text-xs">
                <p className="font-medium text-foreground">Waiting for device connection...</p>
                <p className="text-muted-foreground">
                  The device will generate an Ed25519 keypair and send its public key to the server.
                </p>
              </div>
            </div>

            <DialogFooter className="pt-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Close (Keep waiting in background)
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* STEP 3: Paired Successfully */}
        {step === 3 && (
          <div className="space-y-4 py-4 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-500">
              <CheckCircle2 className="h-8 w-8" />
            </div>
            <div className="space-y-1">
              <h3 className="text-lg font-semibold text-foreground">Device Paired Successfully!</h3>
              <p className="text-sm text-muted-foreground">
                Hardware terminal <code className="font-mono text-foreground">{deviceName}</code> is now
                registered in the device network.
              </p>
            </div>
            <div className="text-xs text-muted-foreground bg-muted p-3 rounded text-left space-y-1">
              <p>• Device Ed25519 public key has been verified and registered.</p>
              <p>• Device private key is securely stored on hardware with POSIX 0600 mode.</p>
              <p>• All subsequent verification requests will be signed and validated.</p>
            </div>
            <DialogFooter className="pt-2">
              <Button onClick={() => onOpenChange(false)} className="w-full">
                Done
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
