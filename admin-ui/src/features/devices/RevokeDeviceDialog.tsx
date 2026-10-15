// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertTriangle } from "lucide-react";

interface RevokeDeviceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  device: { id: string; name: string } | null;
  onConfirm: (deviceId: string, reason: string) => Promise<void>;
  isLoading?: boolean;
}

export const RevokeDeviceDialog: React.FC<RevokeDeviceDialogProps> = ({
  open,
  onOpenChange,
  device,
  onConfirm,
  isLoading = false,
}) => {
  const [confirmText, setConfirmText] = useState("");
  const [reason, setReason] = useState("");

  if (!device) return null;

  const isConfirmed = confirmText.trim() === device.name;

  const handleConfirm = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (!isConfirmed) return;
    await onConfirm(device.id, reason.trim() || "Administrative revocation");
    setConfirmText("");
    setReason("");
    onOpenChange(false);
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="border-destructive/30 max-w-md">
        <AlertDialogHeader>
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5 shrink-0" />
            <AlertDialogTitle>Permanently Revoke Edge Device?</AlertDialogTitle>
          </div>
          <AlertDialogDescription className="space-y-3 pt-2 text-left">
            <p>
              You are about to permanently revoke device{" "}
              <strong className="text-foreground font-mono">{device.name}</strong>.
            </p>
            <div className="rounded-md bg-destructive/10 p-3 text-xs text-destructive font-medium">
              ⚠️ <strong>Irreversible Action:</strong> All subsequent requests signed by this
              device will be rejected immediately (0 ms propagation delay). This device cannot be
              reactivated; it will need to be re-paired from scratch.
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="revoke-reason" className="text-xs">
              Reason for revocation:
            </Label>
            <Input
              id="revoke-reason"
              placeholder="e.g. Device decommissioned, lost hardware, or key compromised"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirm-name" className="text-xs">
              Type <strong className="font-mono text-destructive">{device.name}</strong> to confirm:
            </Label>
            <Input
              id="confirm-name"
              placeholder={device.name}
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="font-mono text-sm"
              autoFocus
            />
          </div>
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => { setConfirmText(""); setReason(""); }}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={!isConfirmed || isLoading}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {isLoading ? "Revoking..." : "Revoke Device Permanently"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
